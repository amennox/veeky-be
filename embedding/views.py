from django.shortcuts import render

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .tasks import train_embedding_model # Importa la task di addestramento
from django_q.tasks import async_task
import torch
import open_clip
from PIL import Image
import base64
from io import BytesIO

class EmbeddingAPIView(APIView):
    def post(self, request, *args, **kwargs):
        input_data = request.data.get("input")
        model_name = request.data.get("model", "default") # 'default' o un nome specifico

        # Carica il modello (logica semplificata)
        model, _, preprocess = open_clip.create_model_and_transforms('ViT-B-32')
        if model_name != "default":
            model_path = f"embedding/models/{model_name}_best.pth"
            try:
                model.load_state_dict(torch.load(model_path))
            except FileNotFoundError:
                return Response({"error": "Modello non trovato"}, status=status.HTTP_404_NOT_FOUND)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        model.eval()

        # Logica per generare l'embedding da un'immagine in base64
        try:
            if input_data.startswith("data:image"):
                input_data = input_data.split(",")[1]
            image_data = base64.b64decode(input_data)
            image = Image.open(BytesIO(image_data)).convert("RGB")
            image_tensor = preprocess(image).unsqueeze(0).to(device)
            with torch.no_grad():
                embedding = model.encode_image(image_tensor)
            return Response({"embedding": embedding.cpu().numpy().tolist()})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class TrainEmbeddingAPIView(APIView):
    def post(self, request, *args, **kwargs):
        category_id = request.data.get("category_id")
        if not category_id:
            return Response({"error": "category_id mancante"}, status=status.HTTP_400_BAD_REQUEST)

        # Avvia la task di addestramento in background
        async_task('embedding.tasks.train_embedding_model', category_id)

        return Response({"message": "Addestramento avviato"}, status=status.HTTP_202_ACCEPTED)