var CONF = {
    image: { width: 50, height: 40 },
    force: { width: window.innerWidth, height: window.innerHeight - 100, dist: 200, charge: -1000 }
};

var svg, force, nodes = [], links = [], node_index = {}, ports_data = [];

function init_d3() {
    svg = d3.select("#topology").append("svg").attr("width", "100%").attr("height", CONF.force.height);
    force = d3.layout.force().size([window.innerWidth, CONF.force.height]).charge(CONF.force.charge).linkDistance(CONF.force.dist).gravity(0.1).friction(0.7).on("tick", _tick);
}

function _tick() {
    svg.selectAll(".link").attr("x1", d => d.source.x).attr("y1", d => d.source.y)
                          .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    
    svg.selectAll(".node").attr("transform", d => {
        d.x = Math.max(25, Math.min(window.innerWidth - 350, d.x));
        d.y = Math.max(20, Math.min(CONF.force.height - 20, d.y));
        return "translate(" + d.x + "," + d.y + ")";
    });


    svg.selectAll(".link-label-tx")
        .attr("x", d => (d.source.x + d.target.x) / 2)
        .attr("y", d => (d.source.y + d.target.y) / 2 - 10);

    svg.selectAll(".link-label-rx")
        .attr("x", d => (d.source.x + d.target.x) / 2)
        .attr("y", d => (d.source.y + d.target.y) / 2 + 10);

    svg.selectAll(".port").attr("transform", d => {
        var weight = d.dir === "target" ? 0.15 : 0.85;
        var link = links[d.link_idx];
        return link ? "translate(" + (link.source.x * weight + link.target.x * (1 - weight)) + "," + (link.source.y * weight + link.target.y * (1 - weight)) + ")" : "";
    });
}

async function load_topology() {
    const res = await fetch('/api/topology_config');
    const data = await res.json();
    nodes = []; links = []; node_index = {}; ports_data = [];

    data.switches.forEach(s => { node_index[s] = nodes.length; nodes.push({ id: s, label: s, type: 'switch' }); });
    Object.keys(data.roles).forEach(hostId => {
        const roleInfo = data.roles[hostId];
        

        const displayName = roleInfo.role; 

        node_index[hostId] = nodes.length; 
        nodes.push({ 
            id: hostId, 
            label: displayName, 
            type: 'host' 
        });
    });

    data.links.forEach((l, i) => {
        var s_idx = node_index[l.node1], t_idx = node_index[l.node2];
        if (s_idx !== undefined && t_idx !== undefined) {
            links.push({ source: s_idx, target: t_idx });
            if (l.node1.startsWith('s')) ports_data.push({ node_name: l.node1, port_no: l.port1, link_idx: i, dir: "source" });
            if (l.node2.startsWith('s')) ports_data.push({ node_name: l.node2, port_no: l.port2, link_idx: i, dir: "target" });
        }
    });
    draw();
}

function draw() {
    force.nodes(nodes).links(links).start();
    svg.selectAll(".link").data(links).enter().append("line").attr("class", "link");

    svg.selectAll(".link-label-tx").data(links).enter().append("text")
        .attr("class", "link-label-tx")
        .style("fill", "#e67e22")
        .style("font-size", "12px").style("font-weight", "bold").attr("text-anchor", "middle");

    svg.selectAll(".link-label-rx").data(links).enter().append("text")
        .attr("class", "link-label-rx")
        .style("fill", "#3498db")
        .style("font-size", "12px").style("font-weight", "bold").attr("text-anchor", "middle");

    
    var port = svg.selectAll(".port").data(ports_data).enter().append("g").attr("class", "port");
    port.append("circle").attr("r", 10).style("fill", "#2ecc71");
    port.append("text").text(d => d.port_no).attr("dx", -4).attr("dy", 4).style("fill", "white").style("font-size", "10px");

    var node = svg.selectAll(".node").data(nodes).enter().append("g").attr("class", "node").call(node_drag);
    node.append("image")
    .attr("xlink:href", d => {

        if (d.type === 'switch') return "/static/router.png";
        

        if (d.id === 'h10') return "/static/server.png"; 
        

        return "/static/host.png";
    })
    .attr("x", -25)
    .attr("y", -20)
    .attr("width", 50)
    .attr("height", 40);
    node.append("text").attr("dy", 35).attr("text-anchor", "middle").text(d => d.label).style("font-weight", "bold");
}

async function update_states() {
    const res = await fetch('/api/port_states');
    const states = await res.json();
    svg.selectAll(".port circle").style("fill", d => {
        var dpid = parseInt(d.node_name.replace('s', ''));
        return (states[dpid] || {})[d.port_no] === 'DOWN' ? "#e74c3c" : "#2ecc71";
    });
}

var node_drag = d3.behavior.drag()
    .on("dragstart", d => force.stop())
    .on("drag", d => { d.px += d3.event.dx; d.py += d3.event.dy; d.x += d3.event.dx; d.y += d3.event.dy; _tick(); })
    .on("dragend", d => { d.fixed = true; force.resume(); });

var ctx = document.getElementById('throughputChart').getContext('2d');
var throughputData = {
    labels: [], 
    datasets: [{
        label: 'Trafic Total (Mbps)',
        borderColor: '#2ecc71',
        backgroundColor: 'rgba(46, 204, 113, 0.1)',
        data: [],
        fill: true,
        borderWidth: 2,
        pointRadius: 0 
    }]
};

var myChart = new Chart(ctx, {
    type: 'line',
    data: throughputData,
    options: {
        animation: { duration: 1000 },
        scales: { y: { beginAtZero: true } }
    }
});

async function update_chart() {
    try {
        const res = await fetch('/api/global_stats');
        const data = await res.json();
        
        document.getElementById('live-total').innerText = data.total_mbps;
        
        var now = new Date();
        var timeLabel = now.getHours() + ":" + now.getMinutes() + ":" + now.getSeconds();
        throughputData.labels.push(timeLabel);
        throughputData.datasets[0].data.push(data.total_mbps);
        if (throughputData.labels.length > 20) {
            throughputData.labels.shift();
            throughputData.datasets[0].data.shift();
        }
        myChart.update();
    } catch (e) {}
}

async function update_link_bandwidth() {
    try {
        const res = await fetch('/api/links_bandwidth_detail');
        const data = await res.json();
        

        console.log("Données reçues:", data);
        

        const firstLink = Object.keys(data)[0];
        if (firstLink) {
            console.log("Premier lien:", firstLink, data[firstLink]);
        }
        
        svg.selectAll(".link-label-tx").text(d => {
            var key = d.source.id + "-" + d.target.id;
            var rev = d.target.id + "-" + d.source.id;
            var entry = data[key] || data[rev];
            if (entry && entry.tx > 0.01) {
                return "↑ " + entry.tx.toFixed(1) + " Mbps";
            }
            return "";
        });

        svg.selectAll(".link-label-rx").text(d => {
            var key = d.source.id + "-" + d.target.id;
            var rev = d.target.id + "-" + d.source.id;
            var entry = data[key] || data[rev];
            if (entry && entry.rx > 0.01) {
                return "↓ " + entry.rx.toFixed(1) + " Mbps";
            }
            return "";
        });
    } catch (e) {
        console.error("Erreur bandwidth:", e);
    }
}

function toggleStats() {
    var overlay = document.getElementById('stats-overlay');
    if (overlay) {
        if (overlay.style.display === "none") {
            overlay.style.display = "block";
        } else {
            overlay.style.display = "none";
        }
    }
}



async function sendMessage() {
    const input = document.getElementById('user-input');
    const chatWindow = document.getElementById('chat-window');
    const message = input.value.trim();
    if (!message) return;


    chatWindow.innerHTML += `<div class="msg user-msg"><b>Vous :</b> ${message}</div>`;
    input.value = '';
    chatWindow.scrollTop = chatWindow.scrollHeight;


    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'msg system-loading';
    loadingDiv.innerHTML = '<span style="color:#888">⏳ Traitement en cours...</span>';
    chatWindow.appendChild(loadingDiv);
    chatWindow.scrollTop = chatWindow.scrollHeight;

    try {
        const response = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: message })
        });
        const data = await response.json();


        loadingDiv.remove();


        chatWindow.innerHTML += `<div class="msg ai-msg"><b>🤖 IA :</b> ${data.response}</div>`;
        chatWindow.scrollTop = chatWindow.scrollHeight;

    } catch (error) {

        loadingDiv.remove();
        
        chatWindow.innerHTML += `<div class="msg error-msg">❌ Erreur: ${error.message}</div>`;
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }
}



document.getElementById('user-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});



const STATUS_LABELS = {
    "ACTIVE":      { label: "Actif",      css: "active"     },
    "DORMANTE":    { label: "En attente", css: "dormante"   },
    "CORRECTING":  { label: "Correction", css: "correcting" },
    "STOPPED":     { label: "Arrêtée",    css: "stopped"    },
};

const ACTION_ICONS = {
    "QOS":          "🎯",
    "NETWORK_WIDE": "🌐",
    "BREAK":        "✂️",
    "RESTORE":      "🔄",
    "QUERY":        "🔍",
};

async function refreshMissions() {
    try {
        const res  = await fetch('/api/missions');
        const data = await res.json();
        renderMissions(data.missions || []);
    } catch (e) {
        console.warn("Missions inaccessibles", e);
    }
}

function renderMissions(missions) {
    const list  = document.getElementById('missions-list');
    const badge = document.getElementById('missions-count');
    badge.textContent = missions.length;

    if (missions.length === 0) {
        list.innerHTML = '<div class="missions-empty">Aucune mission active</div>';
        return;
    }

    list.innerHTML = missions.map(m => {
        const st    = STATUS_LABELS[m.status] || { label: m.status, css: "stopped" };
        const icon  = ACTION_ICONS[m.action]  || "⚙️";
        const hotes = (m.hotes || []).join(', ') || '—';
        const profil = m.profil ? ` · ${m.profil}` : '';

        return `
        <div class="mission-card status-${m.status.toLowerCase()}">
            <button class="btn-delete-mission"
                    onclick="deleteMission('${m.mission_id}')"
                    title="Supprimer la mission">✕</button>
            <div class="mission-id">${m.mission_id}</div>
            <div class="mission-action">${icon} ${m.action}${profil}</div>
            <div class="mission-meta">Hôtes : ${hotes}</div>
            <div class="mission-meta">Depuis ${m.cree_a} · ${m.corrections} correction(s)</div>
            <span class="mission-status ${st.css}">${st.label}</span>
        </div>`;
    }).join('');
}

async function deleteMission(missionId) {
    if (!confirm(`Supprimer la mission ${missionId} ?`)) return;
    try {
        const res  = await fetch(`/api/missions/${missionId}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'success') {
            refreshMissions();
        } else {
            alert(`Erreur : ${data.message}`);
        }
    } catch (e) {
        alert("Erreur de connexion.");
    }
}







setInterval(refreshMissions, 5000);
refreshMissions(); 

init_d3();
load_topology();
setInterval(update_states, 2000);
setInterval(update_link_bandwidth, 3000);
setInterval(update_chart, 2000);


