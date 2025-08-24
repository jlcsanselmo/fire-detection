document.addEventListener("DOMContentLoaded", function () {
    // Variáveis globais para as camadas do mapa
    let queimadasLayer = null;
    let drawnPolygon = null;
    let cicatrizLayer = null;
    let cicatrizVectorLayer = null;

    // Elementos do DOM do painel de controle
    const seletorPeriodo = document.getElementById('seletorPeriodo');
    const containerMensal = document.getElementById('containerMensal');
    const seletorArquivoMensal = document.getElementById('seletorArquivoMensal');
    const containerAnual = document.getElementById('containerAnual');
    const seletorArquivoAnual = document.getElementById('seletorArquivoAnual');
    const btnCarregarDados = document.getElementById('btnCarregarDados');
    const btnAnalisarCicatriz = document.getElementById('btnAnalisarCicatriz');
    const resultadoArea = document.getElementById('resultadoArea');
    const resultadoModal = new bootstrap.Modal(document.getElementById('resultadoModal'));

    // Se tiver o painel, protege os cliques
    const controlPanel = document.getElementById('controlPanel');
    if (controlPanel) {
        L.DomEvent.disableClickPropagation(controlPanel);
    }

    // Inicialização do Mapa
    const map = L.map('map', { center: [-15.78, -47.93], zoom: 4 });
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap' }).addTo(map);

    // Correção para ícones invisíveis do Leaflet
    delete L.Icon.Default.prototype._getIconUrl;
    L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.3/dist/images/marker-icon-2x.png',
        iconUrl: 'https://unpkg.com/leaflet@1.9.3/dist/images/marker-icon.png',
        shadowUrl: 'https://unpkg.com/leaflet@1.9.3/dist/images/marker-shadow.png',
    });

    // Lógica de Desenho
    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);
    const drawControl = new L.Control.Draw({
        draw: { polyline: false, rectangle: true, circle: false, marker: false, circlemarker: false, polygon: true },
        edit: { featureGroup: drawnItems }
    });
    map.addControl(drawControl);

    map.on(L.Draw.Event.CREATED, function (e) {
        drawnItems.clearLayers();
        drawnPolygon = e.layer;
        drawnItems.addLayer(drawnPolygon);
        btnAnalisarCicatriz.disabled = false;
    });

    map.on('draw:deleted', function() {
        drawnPolygon = null;
        btnAnalisarCicatriz.disabled = true;
        if(cicatrizLayer) map.removeLayer(cicatrizLayer);
        if(cicatrizVectorLayer) map.removeLayer(cicatrizVectorLayer);
    });

    // Função para carregar FOCOS de queimada (INPE)
    async function carregarFocosDeQueimada(periodo, arquivo = '') {
        console.log(`Buscando dados para: Período=${periodo}, Arquivo=${arquivo}`);
        map.getContainer().style.cursor = 'wait';

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
                let latStr, lonStr, satelite, dataHora;

                if (periodo === 'mensal' || periodo === 'anual') {
                    if (colunas.length < 5) return;
                    latStr = colunas[1];
                    lonStr = colunas[2];
                    dataHora = colunas[3];
                    satelite = colunas[4];
                } else if (periodo === '10min') {
                    if (colunas.length < 4) return;
                    latStr = colunas[0];
                    lonStr = colunas[1];
                    satelite = colunas[2];
                    dataHora = colunas[3];
                } else {
                    return;
                }
                
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
                } catch (e) { console.warn("Não foi possível processar a linha do CSV:", linha, e); }
            });

            console.log(`Processamento finalizado. Marcadores criados: ${marcadoresCriados}`);
            if (marcadoresCriados > 0) {
                map.addLayer(queimadasLayer);
            } else if (periodo !== '10min') {
                alert("Nenhum foco de queimada encontrado para o período selecionado.");
            }
        } catch (error) {
            console.error("Erro CRÍTICO ao carregar focos de queimada:", error);
            alert("Não foi possível carregar os dados. Verifique o console para mais detalhes.");
        } finally {
            map.getContainer().style.cursor = '';
        }
    }

    // Função para analisar a CICATRIZ (GEE)
    async function analisarCicatriz() {
        if (!drawnPolygon) {
            alert("Por favor, desenhe um polígono no mapa primeiro.");
            return;
        }
        const periodo = seletorPeriodo.value;
        if (periodo === '10min') {
            alert("A análise de cicatriz funciona com períodos históricos. Selecione um Mês ou Ano.");
            return;
        }
        
        const arquivo = periodo === 'mensal' ? seletorArquivoMensal.value : seletorArquivoAnual.value;
        map.getContainer().style.cursor = 'wait';
        btnAnalisarCicatriz.disabled = true;
        btnAnalisarCicatriz.innerHTML = 'Analisando...';

        if (cicatrizLayer) map.removeLayer(cicatrizLayer);
        if (cicatrizVectorLayer) map.removeLayer(cicatrizVectorLayer);

        try {
            const response = await fetch('/analisar-cicatrizes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    geometry: drawnPolygon.toGeoJSON().geometry,
                    arquivo: arquivo
                })
            });

            if (!response.ok) {
                if (response.status === 404 || response.status === 503) {
                    const errorData = await response.json();
                    throw new Error(errorData.error);
                }
                throw new Error("Ocorreu um erro desconhecido no servidor.");
            }
            
            const resultado = await response.json();
            
            if(resultado.area_ha > 0) {
                cicatrizLayer = L.tileLayer(resultado.tile_url, { opacity: 0.75 });
                map.addLayer(cicatrizLayer);

                if (resultado.cicatriz_geojson) {
                    cicatrizVectorLayer = L.geoJSON(resultado.cicatriz_geojson, {
                        style: { color: "#ff0000", weight: 2, opacity: 1, fillOpacity: 0.1 }
                    }).bindPopup(`Área da Cicatriz: ${resultado.area_ha.toLocaleString('pt-BR')} ha`);
                    map.addLayer(cicatrizVectorLayer);
                }
                
                resultadoArea.textContent = `${resultado.area_ha.toLocaleString('pt-BR')} hectares`;
                resultadoModal.show();
            } else {
                alert("Nenhuma cicatriz de queimada com severidade moderada/alta foi encontrada na área e período selecionados.");
            }

        } catch (error) {
            console.error("Erro ao analisar cicatriz:", error);
            alert(error.message);
        } finally {
            map.getContainer().style.cursor = '';
            btnAnalisarCicatriz.disabled = false;
            btnAnalisarCicatriz.innerHTML = 'Analisar Cicatriz';
        }
    }
    
    // Preenche os seletores (mensal e anual)
    async function popularSeletores() {
        try {
            let res = await fetch('/listar-arquivos?periodo=mensal');
            let arquivos = await res.json();
            seletorArquivoMensal.innerHTML = '';
            arquivos.forEach(arq => seletorArquivoMensal.add(new Option(arq.replace('focos_mensal_br_', '').replace('.csv', ''), arq)));

            res = await fetch('/listar-arquivos?periodo=anual');
            arquivos = await res.json();
            seletorArquivoAnual.innerHTML = '';
            arquivos.forEach(arq => seletorArquivoAnual.add(new Option(arq.replace('focos_anuais_brasil_', '').replace('.csv', ''), arq)));
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

    // Ação do botão "Analisar Cicatriz"
    btnAnalisarCicatriz.addEventListener('click', analisarCicatriz);

    // Popular seletores no carregamento inicial
    popularSeletores();
});
