document.addEventListener("DOMContentLoaded", function () {
    let queimadasLayer = null;

    // Elementos do DOM do painel de controle
    const seletorPeriodo = document.getElementById('seletorPeriodo');
    const containerMensal = document.getElementById('containerMensal');
    const seletorArquivoMensal = document.getElementById('seletorArquivoMensal');
    const containerAnual = document.getElementById('containerAnual');
    const seletorArquivoAnual = document.getElementById('seletorArquivoAnual');
    const btnCarregarDados = document.getElementById('btnCarregarDados');

    // Inicialização do Mapa
    const map = L.map('map', { 
        center: [-15.78, -47.93], 
        zoom: 4 
    });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { 
        attribution: '&copy; OpenStreetMap contributors' 
    }).addTo(map);

    // Correção para ícones invisíveis do Leaflet
    delete L.Icon.Default.prototype._getIconUrl;
    L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.3/dist/images/marker-icon-2x.png',
        iconUrl: 'https://unpkg.com/leaflet@1.9.3/dist/images/marker-icon.png',
        shadowUrl: 'https://unpkg.com/leaflet@1.9.3/dist/images/marker-shadow.png',
    });

    // Função principal para buscar e exibir os focos de queimada
async function carregarFocosDeQueimada(periodo, arquivo = '') {
    console.log(`Buscando dados para: Período=${periodo}, Arquivo=${arquivo}`);
    map.getContainer().style.cursor = 'wait'; // Cursor de "carregando"

    try {
        const url = `/dados-queimadas?periodo=${periodo}&arquivo=${arquivo}`;
        const response = await fetch(url);

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`A requisição falhou: ${response.status} ${errorText}`);
        }
        const dataCSV = await response.text();

        if (queimadasLayer) map.removeLayer(queimadasLayer);
        
        queimadasLayer = L.markerClusterGroup();
        const linhas = dataCSV.trim().split('\n');
        linhas.shift(); // Remove o cabeçalho
        let marcadoresCriados = 0;

        linhas.forEach((linha) => {
            const colunas = linha.split(',');
            
            // Variáveis para armazenar os dados extraídos
            let latStr, lonStr, satelite, dataHora;

            // ======================================================================
            // ### LÓGICA EXPLÍCITA PARA CADA FORMATO DE ARQUIVO ###
            // ======================================================================
            if (periodo === 'mensal' || periodo === 'anual') {
                // Formato detalhado para dados mensais e anuais
                if (colunas.length < 5) return; // Pula linha se não tiver colunas suficientes
                latStr = colunas[1];      // Latitude está na coluna 1
                lonStr = colunas[2];      // Longitude está na coluna 2
                dataHora = colunas[3];    // Data está na coluna 3
                satelite = colunas[4];    // Satélite está na coluna 4

            } else if (periodo === '10min') {
                // Formato simples para dados de 10 minutos
                if (colunas.length < 4) return; // Pula linha se não tiver colunas suficientes
                latStr = colunas[0];      // Latitude está na coluna 0
                lonStr = colunas[1];      // Longitude está na coluna 1
                satelite = colunas[2];    // Satélite está na coluna 2
                dataHora = colunas[3];    // Data está na coluna 3
            
            } else {
                return; // Período desconhecido, não faz nada
            }
            
            // Lógica de conversão e criação do marcador (continua a mesma)
            try {
                if (!latStr || !lonStr) return; 

                const latStrCorrigido = latStr.replace(',', '.');
                const lonStrCorrigido = lonStr.replace(',', '.');
                const lat = parseFloat(latStrCorrigido);
                const lon = parseFloat(lonStrCorrigido);

                if (!isNaN(lat) && !isNaN(lon)) {
                    const marker = L.marker([lat, lon]);
                    marker.bindPopup(`<b>Foco de Queimada 🔥</b><br><b>Data/Hora:</b> ${dataHora}<br><b>Satélite:</b> ${satelite}`);
                    queimadasLayer.addLayer(marker);
                    marcadoresCriados++;
                }
            } catch (e) { 
                console.warn("Não foi possível processar a linha do CSV:", linha, e);
            }
        });

        console.log(`Processamento finalizado. Marcadores criados: ${marcadoresCriados}`);
        if (marcadoresCriados > 0) {
            map.addLayer(queimadasLayer);
        } else {
            alert("Nenhum foco de queimada encontrado para o período selecionado.");
        }
    } catch (error) {
        console.error("Erro CRÍTICO ao carregar focos de queimada:", error);
        alert("Não foi possível carregar os dados. Verifique o console para mais detalhes.");
    } finally {
        map.getContainer().style.cursor = ''; // Restaura o cursor
    }
}

    // Preenche os seletores (mensal e anual) buscando a lista no backend
    async function popularSeletores() {
        try {
            let res = await fetch('/listar-arquivos?periodo=mensal');
            let arquivos = await res.json();
            seletorArquivoMensal.innerHTML = '';
            arquivos.forEach(arq => seletorArquivoMensal.add(new Option(arq, arq)));

            res = await fetch('/listar-arquivos?periodo=anual');
            arquivos = await res.json();
            seletorArquivoAnual.innerHTML = '';
            arquivos.forEach(arq => seletorArquivoAnual.add(new Option(arq, arq)));
        } catch (e) {
            console.error("Erro ao popular seletores:", e);
        }
    }

    // Gerencia a visibilidade dos seletores quando o período muda
    seletorPeriodo.addEventListener('change', function() {
        containerMensal.style.display = this.value === 'mensal' ? 'block' : 'none';
        containerAnual.style.display = this.value === 'anual' ? 'block' : 'none';
    });

    // Ação do botão "Carregar Dados"
    btnCarregarDados.addEventListener('click', function() {
        const periodo = seletorPeriodo.value;
        let arquivo = '';
        if (periodo === 'mensal') {
            arquivo = seletorArquivoMensal.value;
        } else if (periodo === 'anual') {
            arquivo = seletorArquivoAnual.value;
        }
        carregarFocosDeQueimada(periodo, arquivo);
    });

    // --- INICIALIZAÇÃO DA PÁGINA ---
    popularSeletores();
    carregarFocosDeQueimada('10min'); // Carrega os dados em tempo real por padrão
});