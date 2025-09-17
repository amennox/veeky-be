# Veeky Backend

This repository contains the **backend service** of the Veeky project.  
The system is a **full-stack containerized web application** for video analysis, indexing, and advanced search.  
The backend is implemented in **Python 3.10** using **Django + Django REST Framework (DRF)**, with **PostgreSQL 16** as relational database and **OpenSearch** for full-text and vector search.  
Asynchronous tasks are handled with **Django-Q**, while **Ollama** provides AI models (e.g., Gemma) for embeddings, transcription, and enrichment.

---

## 🚀 Architecture Overview

The project follows a **decoupled architecture** with:

- **Backend API (Django + DRF)**  
  Exposes REST endpoints for authentication, video management, indexing, and search.

- **Frontend (React SPA)**  
  Consumes the backend API and provides a modern user interface (separate repository).

- **Database (PostgreSQL 16)**  
  Stores users, roles, categories, videos, and configuration entities.

- **Search Engine (OpenSearch)**  
  Stores enriched and indexed video content (text, audio transcription, keyframes, embeddings).

- **AI Models (Ollama)**  
  Used for text embeddings, video keyframe description, keyword extraction, OCR enrichment, and category-specific image embeddings.

- **Asynchronous Worker (Django-Q)**  
  Executes the video processing pipeline (segmentation, transcription, enrichment, indexing).

---

## 🗂️ Backend Project Structure

backend/
│ manage.py
│
├── core/ # Django project settings and entrypoints
│ ├── settings.py
│ ├── urls.py
│ ├── wsgi.py
│ └── asgi.py
│
├── users/ # User management and authentication
│ ├── models.py # Custom User with role & categories
│ ├── serializers.py
│ ├── views.py
│ ├── permissions.py
│ └── urls.py
│
├── videos/ # Video entity and processing status
│ ├── models.py # Video, Category
│ ├── serializers.py
│ ├── views.py
│ ├── permissions.py
│ └── urls.py
│
├── indexing/ # Indexing pipeline orchestration
│ ├── tasks.py # Django-Q tasks for video analysis
│ ├── utils.py
│ ├── opensearch_client.py
│ └── ollama_client.py
│
└── configs/ # Configuration entities (LLM, prompts, endpoints)
├── models.py # Config, Prompt, LLMSetting
├── serializers.py
├── views.py
├── urls.py
└── admin.py


---

## 🔑 Entities

### User Model
- Custom user extending `AbstractUser`
- Fields:
  - `role`: choices (`ADMIN`, `EDITOR`, `USER`)
  - `categories`: many-to-many with `Category`

### Category Model
- `name`: category name (e.g., "Sports", "Documentary")
- `image_embedding_model_name`: name of embedding model used in Ollama

### Video Model
- `title`, `description`
- `category` (FK to Category)
- `keywords` (tags)
- `uploader` (FK to User)
- `video_file` (uploaded video)
- `status`: (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`)
- `opensearch_parent_id`: link to OpenSearch parent document

### Configs App
Centralized configuration for AI/LLM:
- `Config`: generic key-value settings
- `Prompt`: prompt templates for Ollama
- `LLMSetting`: model name, temperature, max tokens, etc.

---

## ⚙️ Video Indexing Pipeline

The **`process_video_task`** handles video processing asynchronously:

1. **Initialization**
   - Sets video status to `PROCESSING`.

2. **Video Analysis**
   - Extracts segments with `ffmpeg` + `scenedetect`.
   - Extracts keyframes for each segment.

3. **OpenSearch Parent Document**
   - Creates parent doc with metadata: title, description, keywords.

4. **Segment Processing**
   - **Audio transcription** → Whisper
   - **Text enrichment** → Ollama (keywords + embeddings)
   - **Keyframe analysis**:
     - Image description via Ollama
     - OCR text extraction
     - Image embeddings with category-specific model
   - Indexed as child documents in OpenSearch.

5. **Finalization**
   - Sets video status to `COMPLETED` or `FAILED`.

---

## 🔐 Roles & Permissions

- **Admin** → Full access (`IsAdminUser`)  
- **Editor** → Can upload/manage videos (`IsEditorUser`)  
- **User** → Can only view videos within allowed categories (`CanViewCategory`)  

---

## 📡 API Endpoints (DRF)

- `/api/auth/` → Authentication (local or OIDC, `dj-rest-auth`)
- `/api/videos/` → Video upload & management
- `/api/videos/{id}/status/` → Polling for video processing status
- `/api/search/` → Search endpoint querying OpenSearch
- `/api/configs/` → CRUD for configs, prompts, and LLM settings

---

## 📝 Code Style Requirements

⚠️ **Important rule for Codex and developers:**  
All **class names, variables, functions, and comments must be written in English**.  
This ensures consistency across the backend and AI code generation workflows.

---

## 🐳 Dockerized Environment

The entire project runs via `docker-compose.yml` with the following services:

- `backend` → Django + Gunicorn
- `frontend` → React SPA
- `db` → PostgreSQL 16
- `opensearch` → OpenSearch latest
- `django_q_worker` → Worker for async tasks
- `ollama` → AI model server

---

## ✅ Next Steps

- Implement database models
- Write serializers and permissions
- Implement video processing pipeline in `indexing/tasks.py`
- Connect backend to OpenSearch and Ollama
- Add unit tests

---

## Virtual Ambient
python -m venv venv
.\venv\Scripts\Activate.ps1