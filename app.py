from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import ee

# --- INICIALIZAÇÃO DO EARTH ENGINE ---
try:

    ee.Initialize()
except Exception:
    ee.Authenticate()
    ee.Initialize(project='ee-jlcsanselmo') #  ID 


app = Flask(__name__)

# --- FUNÇÃO DE PROCESSAMENTO GEE ---
def processar_imagens_gee(roi, data_inicio, data_fim):
    """
    Executa o fluxo de trabalho de análise de cicatrizes de queimada no Google Earth Engine.
    """
    # 1. Seleção e filtro de imagens Sentinel-2
    colecao_imagens = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                       .filterBounds(roi)
                       .filterDate(ee.Date(data_inicio), ee.Date(data_fim)))

    # 2. Função para mascarar (remover) nuvens
    def mascarar_nuvens_s2(imagem):
        qa = imagem.select('QA60')
        cloud_bit_mask = 1 << 10
        cirrus_bit_mask = 1 << 11
        mascara = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(
                  qa.bitwiseAnd(cirrus_bit_mask).eq(0))
        return imagem.updateMask(mascara).divide(10000)

    colecao_sem_nuvens = colecao_imagens.map(mascarar_nuvens_s2)

    # 3. Criação de um mosaico (imagem única sem nuvens) usando a mediana
    mosaico = colecao_sem_nuvens.median().clip(roi)
    
    # 4. Cálculo do NBR (Normalized Burn Ratio)
    imagem_nbr = mosaico.normalizedDifference(['B8', 'B12'])

    # Retornamos a imagem NBR para ser usada no cálculo do dNBR
    return imagem_nbr

# --- ROTAS FLASK ---

@app.route("/")
def index():
    return render_template("index.html")

# Rota para listar arquivos do INPE
@app.route('/listar-arquivos')
def listar_arquivos():
    periodo = request.args.get('periodo')
    if periodo == 'mensal':
        url = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/"
    elif periodo == 'anual':
        url = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/"
    else:
        return jsonify({"error": "Período inválido"}), 400
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        csv_files = [a['href'] for a in soup.find_all('a') if a.get('href', '').endswith('.csv')]
        csv_files.reverse()
        return jsonify(csv_files)
    except Exception as e:
        return jsonify({"error": "Não foi possível listar os arquivos."}), 500

# Rota para buscar dados de focos do INPE
@app.route('/dados-queimadas')
def proxy_queimadas():
    periodo = request.args.get('periodo', '10min')
    arquivo = request.args.get('arquivo', '')
    base_url = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/"
    target_url = ""
    try:
        if periodo == '10min':
            dir_url = f"{base_url}10min/"
            headers = {'User-Agent': 'Mozilla/5.0'}
            dir_response = requests.get(dir_url, headers=headers, timeout=15, verify=False)
            dir_response.raise_for_status()
            soup = BeautifulSoup(dir_response.text, 'html.parser')
            csv_files = [a['href'] for a in soup.find_all('a') if a.get('href', '').endswith('.csv')]
            if not csv_files: raise ValueError("Nenhum arquivo de 10 minutos encontrado.")
            target_url = f"{dir_url}{csv_files[-1]}"
        elif periodo == 'mensal':
            target_url = f"{base_url}mensal/Brasil/{arquivo}"
        elif periodo == 'anual':
            target_url = f"{base_url}anual/{arquivo}"
        else: return "Período inválido.", 400
        headers = {'User-Agent': 'Mozilla/5.0'}
        csv_response = requests.get(target_url, headers=headers, timeout=30, verify=False)
        csv_response.raise_for_status()
        return csv_response.text, 200, {'Content-Type': 'text/csv; charset=utf-8'}
    except Exception as e:
        return "Não foi possível buscar os dados do INPE.", 503

# Rota para Análise de Cicatrizes com GEE
@app.route('/analisar-cicatrizes', methods=['POST'])
def analisar_cicatrizes():
    data = request.get_json(force=True)
    geojson = data['geometry']
    arquivo = data['arquivo']

    try:
        parts = arquivo.split('_')[-1].replace('.csv', '')
        year = int(parts[:4])
        month = int(parts[4:])
    except:
        return jsonify({"error": "Nome de arquivo inválido para extrair data."}), 400

    # Define os períodos pré e pós-fogo
    post_fire_start = ee.Date.fromYMD(year, month, 1)
    post_fire_end = post_fire_start.advance(1, 'month')
    pre_fire_start = post_fire_start.advance(-1, 'year')
    pre_fire_end = post_fire_end.advance(-1, 'year')

    roi = ee.Geometry.Polygon(geojson['coordinates'])

    # Coleção de imagens e função de máscara de nuvens
    collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(roi)
    def mask_s2_clouds(image):
        qa = image.select('QA60')
        cloud_bit_mask = 1 << 10
        cirrus_bit_mask = 1 << 11
        mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
        return image.updateMask(mask).divide(10000)

    # Filtra as coleções para os dois períodos
    pre_fire_collection = collection.filterDate(pre_fire_start, pre_fire_end)
    post_fire_collection = collection.filterDate(post_fire_start, post_fire_end)
    
    # =================================================================
    # ### NOVA VERIFICAÇÃO DE ROBUSTEZ ###
    # Verifica se as coleções de imagens não estão vazias ANTES de processar
    # =================================================================
    if pre_fire_collection.size().getInfo() == 0 or post_fire_collection.size().getInfo() == 0:
        return jsonify({
            "error": "Não foram encontradas imagens de satélite sem nuvens para o período selecionado. Por favor, tente um mês ou ano diferente."
        }), 404 # Usamos o status 404 (Not Found) para este erro específico

    # Se as coleções não estiverem vazias, o processamento continua...
    pre_fire_img = pre_fire_collection.map(mask_s2_clouds).median().clip(roi)
    post_fire_img = post_fire_collection.map(mask_s2_clouds).median().clip(roi)
    
    pre_nbr = pre_fire_img.normalizedDifference(['B8', 'B12'])
    post_nbr = post_fire_img.normalizedDifference(['B8', 'B12'])
    dnbr = pre_nbr.subtract(post_nbr)

    # Vetoriza a cicatriz e calcula a área
    limiar_severidade = 0.27
    burned_mask = dnbr.gte(limiar_severidade).selfMask()
    vetores = burned_mask.reduceToVectors(
      geometry=roi, scale=10, geometryType='polygon', eightConnected=False, maxPixels=1e13
    )
    geometria_dissolvida = vetores.geometry().dissolve(maxError=1)
    area_ha = ee.Number(geometria_dissolvida.area(maxError=1)).divide(10000).getInfo()

    # Gera a URL do tile
    palette = ['yellow', 'orange', 'red', 'purple']
    vis_params = {'min': 0.1, 'max': 0.7, 'palette': palette}
    map_id = dnbr.getMapId(vis_params)
    tile_url = map_id['tile_fetcher'].url_format

    return jsonify({
        'area_ha': round(area_ha, 2),
        'tile_url': tile_url,
        'cicatriz_geojson': geometria_dissolvida.getInfo()
    })

if __name__ == "__main__":
    app.run(debug=True)