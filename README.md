# Intent-Based Networking (IBN) — SDN, Network Automation & AI

An academic **Intent-Based Networking (IBN)** prototype that converts high-level network intents expressed in natural language into SDN actions, then monitors their enforcement and can trigger corrective actions when a policy is violated.

The project combines **Ryu / OpenFlow 1.3**, **Mininet**, **Open vSwitch**, **Python**, a **Flask REST API**, **QoS/DSCP**, classical Machine Learning and an **LLM orchestration layer**.

> Academic project developed at the École Nationale d'Ingénieurs de Tunis (ENIT), Telecommunications Engineering, 2025–2026.

## What the system does

The prototype implements an end-to-end IBN workflow:

1. A user expresses an intent in natural language.
2. The intent-processing layer identifies the requested action and network entities.
3. The intent is formalized into an executable network policy.
4. The SDN layer applies the policy through Ryu and OpenFlow.
5. Telemetry continuously observes network state and traffic.
6. The assurance layer checks whether active intents remain satisfied and can initiate corrective actions.

Supported use cases include:

- isolating or reconnecting a host (`BREAK` / `RESTORE`);
- assigning QoS policies to traffic (`QOS`);
- applying network-wide QoS policies (`NETWORK_WIDE`);
- DSCP-based traffic differentiation and Open vSwitch queues;
- network telemetry and congestion detection;
- intent monitoring and autonomous policy correction.

## Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                    INTENT / AI LAYER                         │
│ Natural language → classification → extraction → manifest   │
│              TF-IDF + SVM / LangChain + LLM                 │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│                 MANAGEMENT & ASSURANCE                       │
│ Flask REST API • Intent Registry • Policy Validator          │
│ Telemetry • Congestion Detection • Corrective Actions        │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│                       SDN CONTROL                            │
│        Ryu Controller • OpenFlow 1.3 • QoS / DSCP           │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│                    EMULATED NETWORK                          │
│        Mininet • Open vSwitch • 9 switches • 10 hosts       │
└──────────────────────────────────────────────────────────────┘
```

The emulated enterprise topology contains **9 Open vSwitch switches and 10 hosts**, organized as an access/distribution/core hierarchy.

## QoS profiles

The intent engine can map requested service levels to Open vSwitch queues and DSCP markings.

| Profile | Queue | DSCP | PHB |
|---|---:|---:|---|
| STANDARD | Q0 | 0 | Best Effort |
| MULTIMEDIA | Q1 | 34 | AF41 |
| BRONZE | Q2 | 10 | AF11 |
| GOLD | Q3 | 46 | EF |
| SILVER | Q4 | 26 | AF31 |

## Technology stack

| Area | Technologies |
|---|---|
| SDN | Ryu, OpenFlow 1.3, Open vSwitch |
| Emulation | Mininet |
| Backend / API | Python, Flask, REST API |
| Intent processing | TF-IDF, SVM, scikit-learn |
| AI orchestration | LangChain, Groq / LLM |
| Assurance | Random Forest, telemetry, policy validation |
| Traffic policies | QoS, DSCP, HTB / OVS queues |
| Visualization | HTML, JavaScript, Flask dashboard |

## Repository structure

```text
.
├── Api/                    # Flask API, dashboard and network management
├── LangChain_Tool/         # Intent processing and assurance logic
│   ├── Control/            # Telemetry / mission monitoring / validation
│   └── Extracteur/         # Classification and entity extraction
├── automatisation/         # Topology generation and traffic simulation
│   └── topologie/          # Mininet topology and topology definition
├── ryu/                    # Ryu controller and QoS telemetry application
├── Start-mininet.sh        # Mininet launcher
├── requirements.txt        # Python dependencies
└── README.md
```

## Requirements

This project targets a Linux SDN lab environment. You need:

- Python 3;
- Mininet;
- Open vSwitch;
- a Ryu-compatible Python environment;
- `iperf` for traffic-generation experiments;
- the Python packages listed in `requirements.txt`.

Create and activate a virtual environment before installing Python dependencies when possible.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Ryu, Mininet and Open vSwitch may require system-level installation and privileges depending on your Linux distribution. The project was designed for a controlled emulation/lab environment rather than production deployment.

## LLM configuration

The LLM integration uses a local environment variable for the Groq API key. **Never commit a real API key.**

```bash
cp LangChain_Tool/.env.example LangChain_Tool/.env
```

Then edit the local `.env` file:

```env
GROQ_API_KEY=your_api_key_here
```

The `.env` file is excluded by `.gitignore`.

## Running the prototype

Open separate terminals for the main components.

### 1. Start the Ryu controller

```bash
cd ryu
./Start-ryu.sh
```

The launcher starts the custom switching and telemetry applications together with Ryu QoS services.

### 2. Start the Mininet topology

From the repository root:

```bash
./Start-mininet.sh
```

### 3. Start the management API and dashboard

```bash
cd Api
./Start-api.sh
```

Then open:

```text
http://localhost:5000/dashboard
```

## Example intent workflow

Examples handled by the intent-processing logic include requests conceptually equivalent to:

```text
Isolate h1 from the network.
Restore the connection of h3.
Apply GOLD QoS between two hosts.
Apply a SILVER policy to the network.
```

The pipeline classifies the request, extracts the relevant hosts/profile/path information, formalizes the intent and invokes the corresponding network-management action.

## Autonomous assurance

The project goes beyond one-shot intent execution. Active missions can be registered and monitored against network telemetry. The assurance components include:

- collection of network state and traffic metrics;
- policy validation;
- congestion-state classification;
- monitoring of active intents;
- corrective logic when the observed state no longer satisfies a monitored policy.

This creates a closed-loop workflow:

```text
INTENT → TRANSLATE → ENFORCE → MONITOR → VALIDATE → CORRECT
                              ▲                    │
                              └────────────────────┘
```

## Dashboard and REST API

The Flask application exposes a dashboard and endpoints for topology state, link actions, QoS, DSCP policies, telemetry, AI interaction and mission management. The API is intended for the local emulation environment.

Examples of available endpoint families include:

```text
/dashboard
/link/<action>
/qos/network_wide
/qos/set_qos_profile
/api/port_states
/api/global_stats
/api/links_bandwidth
/dscp/set
/dscp/remove
/api/ai/chat
/api/missions
```

## Security note

This repository is a sanitized public version of the academic project. Local environment files, API credentials, Python caches, editor temporary files and machine-specific absolute paths are intentionally excluded.

Before publishing any fork or derivative version, verify that no credentials are present in the Git history or configuration files.

## Project context

This project was developed as a second-year engineering academic project in Telecommunications at **ENIT (École Nationale d'Ingénieurs de Tunis)** during the **2025–2026 academic year**.

**Authors:** Yannick Wendyaoda Dima and Siwar Dridi  
**Academic supervisor:** Meriem Kassar

## Disclaimer

This repository is an educational and research prototype built for an emulated SDN environment. It is not intended to be deployed directly on a production network without additional security, reliability and operational validation.
