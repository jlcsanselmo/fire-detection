from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import ee

# --- INICIALIZAÇÃO DO EARTH ENGINE ---
try:
    # Tenta inicializar com as credenciais já existentes.
    ee.Initialize()
except Exception:
    # Se falhar, inicia o fluxo de autenticação (necessário na primeira vez).
    ee.Authenticate()
    # IMPORTANTE: Insira o ID do seu projeto GEE aqui
    ee.Initialize(project='ee-jlcsanselmo')

app = Flask(__name__)

# --- CABEÇALHOS PARA SIMULAR UM NAVEGADOR E EVITAR BLOQUEIOS ---
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pt;q=0.8",
    "Connection": "keep-alive",
}

# --- FUNÇÃO DE PROCESSAMENTO GEE ---
def processar_imagem_periodo(roi, data_inicio, data_fim):
    """
    Busca, filtra, remove nuvens e cria uma imagem de mosaico para um período.
    """
    collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                    .filterBounds(roi)
                    .filterDate(ee.Date(data_inicio), ee.Date(data_fim)))

    # Verifica se a coleção de imagens não está vazia
    if collection.size().getInfo() == 0:
        return None  # Retorna None se não houver imagens

    def mask_s2_clouds(image):
        qa = image.select('QA60')
        cloud_bit_mask = 1 << 10
        cirrus_bit_mask = 1 << 11
        mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(
            qa.bitwiseAnd(cirrus_bit_mask).eq(0)
        )
        return image.updateMask(mask).divide(10000)

    mosaico = collection.map(mask_s2_clouds).median().clip(roi)
    return mosaico


# --- ROTAS FLASK ---

@app.route("/")
def index():
    return render_template("index.html")


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
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=15, verify=False)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        csv_files = [a['href'] for a in soup.find_all('a') if a.get('href', '').endswith('.csv')]
        csv_files.reverse()
        return jsonify(csv_files)
    except Exception as e:
        print(f"Erro ao listar arquivos para o período '{periodo}': {e}")
        return jsonify({"error": "Não foi possível listar os arquivos."}), 500


@app.route('/dados-queimadas')
def proxy_queimadas():
    periodo = request.args.get('periodo', '10min')
    arquivo = request.args.get('arquivo', '')
    base_url = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/"
    target_url = ""
    try:
        if periodo == '10min':
            dir_url = f"{base_url}10min/"
            dir_response = requests.get(dir_url, headers=BROWSER_HEADERS, timeout=15, verify=False)
            dir_response.raise_for_status()
            soup = BeautifulSoup(dir_response.text, 'html.parser')
            csv_files = [a['href'] for a in soup.find_all('a') if a.get('href', '').endswith('.csv')]
            if not csv_files:
                raise ValueError("Nenhum arquivo de 10 minutos encontrado.")
            target_url = f"{dir_url}{csv_files[-1]}"
        elif periodo == 'mensal':
            target_url = f"{base_url}mensal/Brasil/{arquivo}"
        elif periodo == 'anual':
            target_url = f"{base_url}anual/{arquivo}"
        else:
            return "Período inválido.", 400

        print(f"Buscando dados de: {target_url}")
        csv_response = requests.get(target_url, headers=BROWSER_HEADERS, timeout=60, verify=False)
        csv_response.raise_for_status()
        return csv_response.text, 200, {'Content-Type': 'text/csv; charset=utf-8'}
    except Exception as e:
        print(f"Erro ao buscar dados do INPE: {e}")
        return "Não foi possível buscar os dados do INPE.", 503


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

    post_fire_start = ee.Date.fromYMD(year, month, 1)
    post_fire_end = post_fire_start.advance(1, 'month')
    pre_fire_start = post_fire_start.advance(-1, 'year')
    pre_fire_end = post_fire_end.advance(-1, 'year')   # corrigido

    # Aceita qualquer GeoJSON válido
    roi = ee.Geometry(geojson)

    pre_fire_img = processar_imagem_periodo(roi, pre_fire_start, pre_fire_end)
    post_fire_img = processar_imagem_periodo(roi, post_fire_start, post_fire_end)

    if pre_fire_img is None or post_fire_img is None:
        return jsonify({
            "error": "Não foram encontradas imagens de satélite sem nuvens para o período selecionado. Por favor, tente um mês ou ano diferente."
        }), 404

    def calcular_nbr(imagem):
        nir = imagem.select('B8')
        swir = imagem.select('B12')
        swir_reamostrado = swir.resample('bilinear').reproject(crs=nir.projection())
        return nir.subtract(swir_reamostrado).divide(nir.add(swir_reamostrado)).rename('NBR')

    pre_nbr = calcular_nbr(pre_fire_img)
    post_nbr = calcular_nbr(post_fire_img)
    dnbr = pre_nbr.subtract(post_nbr)

    limiar_severidade = 0.27
    burned_mask = dnbr.gte(limiar_severidade).selfMask()
    vetores = burned_mask.reduceToVectors(
        geometry=roi, scale=10, geometryType='polygon', eightConnected=False, maxPixels=1e13
    )
    geometria_dissolvida = vetores.geometry().dissolve(maxError=1)
    area_ha = ee.Number(geometria_dissolvida.area(maxError=1)).divide(10000).getInfo()

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
