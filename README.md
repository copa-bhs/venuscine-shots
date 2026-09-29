# ReelShort API

API em Python (Flask) que serve o catálogo do ReelShort via scraping,
com paginação real e cache.

## 🌐 Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/health` | Status do servidor |
| `GET` | `/api/home` | Vitrine (slide + seções da home) |
| `GET` | `/api/shorts?page=1&pageSize=24` | Catálogo paginado |
| `GET` | `/api/search?q=...` | Busca por nome |
| `GET` | `/api/categories` | Lista de categorias |
| `GET` | `/api/shorts/<slug>/episodes` | Episódios de um short |
| `GET` | `/api/image?url=...` | Proxy de imagem |

## 🚀 Rodar local

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

pip install -r requirements.txt
python server.py