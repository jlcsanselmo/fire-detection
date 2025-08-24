from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup


app = Flask(__name__)

# Rota principal que serve a página HTML
@app.route("/")
def index():
    return render_template("index.html")

# Rota para listar os arquivos disponíveis (mensais ou anuais)
@app.route('/listar-arquivos')
def listar_arquivos():
    periodo = request.args.get('periodo') # Recebe 'mensal' ou 'anual'
    
    # Links corretos que você forneceu
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
        csv_files.reverse() # Inverte para mostrar os mais recentes primeiro
        return jsonify(csv_files)
    except Exception as e:
        print(f"Erro ao listar arquivos para o período '{periodo}': {e}")
        return jsonify({"error": f"Não foi possível listar os arquivos."}), 500

# Rota para buscar os dados do CSV escolhido
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
            if not arquivo: raise ValueError("Nome do arquivo mensal não fornecido.")
            target_url = f"{base_url}mensal/Brasil/{arquivo}"
        elif periodo == 'anual':
            if not arquivo: raise ValueError("Nome do arquivo anual não fornecido.")
            target_url = f"{base_url}anual/Brasil_todos_sats{arquivo}"
        else:
            return "Período inválido.", 400

        print(f"Buscando dados de: {target_url}")
        headers = {'User-Agent': 'Mozilla/5.0'}
        csv_response = requests.get(target_url, headers=headers, timeout=30, verify=False)
        csv_response.raise_for_status()
        
        return csv_response.text, 200, {'Content-Type': 'text/csv; charset=utf-8'}

    except Exception as e:
        print(f"Erro ao buscar dados do INPE: {e}")
        return "Não foi possível buscar os dados do INPE.", 503

if __name__ == "__main__":
    app.run(debug=True)