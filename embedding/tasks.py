# embedding/tasks.py

import torch
import open_clip
from PIL import Image
import json
from torch.utils.data import Dataset, DataLoader
from pathlib import Path
from videos.models import Category

def train_embedding_model(category_id):
    """
    Task di Django-Q per addestrare un modello di embedding per una categoria specifica.
    """
    try:
        category = Category.objects.get(id=category_id)
    except Category.DoesNotExist:
        print(f"Categoria con ID {category_id} non trovata.")
        return

    # Carica il modello base
    model, _, preprocess = open_clip.create_model_and_transforms('ViT-B-32')
    tokenizer = open_clip.get_tokenizer('ViT-B-32')

    # Carica il dataset (presumendo che sia già stato generato)
    dataset_path = Path("path/to/your/training_dataset.json") # Sostituisci con il percorso corretto
    if not dataset_path.exists():
        print(f"Dataset non trovato in {dataset_path}")
        return

    dataset = UIDataset(str(dataset_path), preprocess)
    dataloader = DataLoader(dataset, batch_size=4, shuffle=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-7)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)

    best_loss = float("inf")
    for epoch in range(10): # Numero di epoche
        model.train()
        total_loss = 0.0
        for imgs, texts in dataloader:
            texts_tok = tokenizer(texts).to(device)
            optimizer.zero_grad()
            image_features, text_features, logit_scale = model(imgs.to(device), texts_tok)

            # Calcolo della loss (esempio con contrastive loss)
            logits_per_image = logit_scale.exp() * image_features @ text_features.t()
            logits_per_text = logits_per_image.t()
            labels = torch.arange(len(imgs), device=device)
            loss_i = torch.nn.functional.cross_entropy(logits_per_image, labels)
            loss_t = torch.nn.functional.cross_entropy(logits_per_text, labels)
            loss = (loss_i + loss_t) / 2

            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        avg_loss = total_loss / len(dataloader)
        print(f"Epoch {epoch + 1}, Loss: {avg_loss}")
        if avg_loss < best_loss:
            best_loss = avg_loss
            model_path = Path(f"embedding/models/{category.name}_best.pth")
            model_path.parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), model_path)
            category.embedding_model_path = str(model_path)
            category.save()
            print(f"Nuovo modello salvato in {model_path}")

class UIDataset(Dataset):
    def __init__(self, json_path, transform):
        with open(json_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        self.transform = transform

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        item = self.data[idx]
        img = Image.open(item["image_path"]).convert("RGB")
        return self.transform(img), item["description"]