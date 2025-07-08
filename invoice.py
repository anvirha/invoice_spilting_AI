import os
import base64
import json
from datetime import datetime
from pymongo import MongoClient
from PyPDF2 import PdfReader, PdfWriter
import google.generativeai as genai
from PIL import Image

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "invoice_db"

def get_base_filename(path):
    return os.path.splitext(os.path.basename(path))[0]

def save_metadata_to_mongodb(metadata, source_file):
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        collection = db["all_invoices"]  # Use a fixed collection name
        result = collection.insert_one(metadata)
        print(f"Metadata inserted into 'all_invoices' with _id: {result.inserted_id}")
    except Exception as e:
        print(f"Failed to insert metadata into MongoDB: {str(e)}")

def has_more_than_two_pages(pdf_path):
    reader = PdfReader(pdf_path)
    return len(reader.pages) > 2

def analyze_document(file_path, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro",
            generation_config={"temperature": 0.1, "top_p": 1, "max_output_tokens": 2048}
        )

        mime_type = "application/pdf" if file_path.lower().endswith('.pdf') else "image/jpeg"
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        prompt = """You are a document analyst. Your task is to detect all DISTINCT invoices in this file.

Return data in this exact JSON format:
[
  {"invoice_number": "INV-001", "page_numbers": [1, 2], "invoice_type": "type like GST, Proforma, tax, e-invoice etc", "hotel_name": "Hotel A"},
  {"invoice_number": "INV-002", "page_numbers": [3], "invoice_type": "type like GST, Proforma, tax, e-invoice etc.", "hotel_name": "Hotel B"}
]

Rules:
- If the file is an image, 'page_numbers' can be omitted or null.
- Only return the JSON array — nothing else.
- Return an empty array if no invoice found.
"""

        parts = [
            prompt,
            {"mime_type": mime_type, "data": base64.b64encode(file_bytes).decode("utf-8")}
        ]

        response = model.generate_content(parts)

        try:
            result = json.loads(response.text.strip())
        except json.JSONDecodeError:
            if '```json' in response.text:
                result = json.loads(response.text.split('```json')[1].split('```')[0])
            elif '```' in response.text:
                result = json.loads(response.text.split('```')[1])
            else:
                raise ValueError("Invalid JSON format")

        return result
    except Exception as e:
        print(f"Gemini error: {str(e)}")
        return []

def save_invoice_pages(pdf_path, start_page, end_page, output_dir="invoice_pages"):
    try:
        base_name = get_base_filename(pdf_path)
        base_dir = os.path.join(output_dir, base_name)
        os.makedirs(base_dir, exist_ok=True)

        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        for page_num in range(start_page, end_page + 1):
            writer.add_page(reader.pages[page_num])

        output_path = os.path.join(base_dir, f"{base_name}_page_{start_page + 1}-{end_page + 1}.pdf")
        with open(output_path, 'wb') as f:
            writer.write(f)

        return output_path
    except Exception as e:
        print(f"PDF splitting error: {str(e)}")
        return None

def split_image_if_needed(image_path, invoices, output_dir="invoice_pages"):
    try:
        image = Image.open(image_path)
        width, height = image.size
        base_name = get_base_filename(image_path)
        base_dir = os.path.join(output_dir, base_name)
        os.makedirs(base_dir, exist_ok=True)

        pdf_paths_metadata = []

        if len(invoices) == 1:
            pdf_path = os.path.join(base_dir, f"{base_name}.pdf")
            image.convert("RGB").save(pdf_path, "PDF", resolution=100.0)

            invoice = invoices[0]
            pdf_paths_metadata.append({
                "invoice_number": invoice.get("invoice_number"),
                "page_range": None,
                "total_pages": 1,
                "saved_pdf_path": os.path.abspath(pdf_path),
                "invoice_type": invoice.get("invoice_type", "Unknown"),
                "hotel_name": invoice.get("hotel_name", "Unknown"),
                "split_method": "full_image",
                "part_number": None,
                "status": "Success",
                "error_message": ""
            })

            return pdf_paths_metadata

        # If multiple invoices, split image in halves (max 2 supported here)
        top_half = image.crop((0, 0, width, height // 2))
        bottom_half = image.crop((0, height // 2, width, height))

        for idx, (img_part, invoice) in enumerate(zip([top_half, bottom_half], invoices), start=1):
            pdf_path = os.path.join(base_dir, f"{base_name}_part_{idx}.pdf")
            img_part.convert("RGB").save(pdf_path, "PDF", resolution=100.0)

            pdf_paths_metadata.append({
                "invoice_number": invoice.get("invoice_number"),
                "page_range": None,
                "total_pages": 1,
                "saved_pdf_path": os.path.abspath(pdf_path),
                "invoice_type": invoice.get("invoice_type", "Unknown"),
                "hotel_name": invoice.get("hotel_name", "Unknown"),
                "split_method": "image_half",
                "part_number": idx,
                "status": "Success",
                "error_message": ""
            })

        return pdf_paths_metadata

    except Exception as e:
        print(f"Image splitting error: {str(e)}")
        metadata = {
            "invoice_number": None,
            "page_range": None,
            "total_pages": None,
            "saved_pdf_path": None,
            "processed_at": datetime.utcnow().isoformat(),
            "source_pdf": os.path.basename(image_path),
            "invoice_type": None,
            "hotel_name": None,
            "status": "Failed",
            "error_message": str(e)
        }
        save_metadata_to_mongodb(metadata, image_path)
        return []

def process_file(file_path, api_key):
    ext = os.path.splitext(file_path)[1].lower()
    invoices = analyze_document(file_path, api_key)

    if not invoices:
        print(f"No invoice found in {file_path}")
        metadata = {
            "invoice_number": None,
            "page_range": None,
            "total_pages": None,
            "saved_pdf_path": None,
            "processed_at": datetime.utcnow().isoformat(),
            "source_pdf": os.path.basename(file_path),
            "invoice_type": None,
            "hotel_name": None,
            "status": "Failed",
            "error_message": "No invoice found"
        }
        save_metadata_to_mongodb(metadata, file_path)
        return

    if ext == ".pdf":
        if not has_more_than_two_pages(file_path):
            print(f"Skipping {file_path} (<=2 pages)")
            return

        all_invoice_metadata = []

        for inv in invoices:
            page_nums = inv.get("page_numbers", [])
            if not page_nums:
                continue

            start_page_1_based = min(page_nums)
            end_page_1_based = max(page_nums)
            start_page_0_based = start_page_1_based - 1
            end_page_0_based = end_page_1_based - 1

            saved_path = save_invoice_pages(file_path, start_page_0_based, end_page_0_based)

            invoice_metadata = {
                "invoice_number": inv.get("invoice_number"),
                "page_range": [start_page_1_based, end_page_1_based],
                "total_pages": end_page_1_based - start_page_1_based + 1,
                "saved_pdf_path": os.path.abspath(saved_path) if saved_path else None,
                "invoice_type": inv.get("invoice_type", "Unknown"),
                "hotel_name": inv.get("hotel_name", "Unknown"),
                "status": "Success" if saved_path else "Failed",
                "error_message": "" if saved_path else "Failed to save PDF"
            }

            all_invoice_metadata.append(invoice_metadata)

        # Save all invoices metadata together for this file
        file_metadata = {
            "source_pdf": os.path.basename(file_path),
            "processed_at": datetime.utcnow().isoformat(),
            "total_invoices": len(all_invoice_metadata),
            "invoices": all_invoice_metadata,
            "status": "Success",
            "error_message": ""
        }
        save_metadata_to_mongodb(file_metadata, file_path)

    elif ext in [".jpg", ".jpeg", ".png"]:
        invoice_metadata_list = split_image_if_needed(file_path, invoices)

        # Save all invoices metadata together for this image file
        file_metadata = {
            "source_pdf": os.path.basename(file_path),
            "processed_at": datetime.utcnow().isoformat(),
            "total_invoices": len(invoice_metadata_list),
            "invoices": invoice_metadata_list,
            "status": "Success" if invoice_metadata_list else "Failed",
            "error_message": "" if invoice_metadata_list else "Failed to process image invoices"
        }
        save_metadata_to_mongodb(file_metadata, file_path)

def process_folder(folder_path, api_key):
    for filename in os.listdir(folder_path):
        full_path = os.path.join(folder_path, filename)
        if os.path.isfile(full_path) and os.path.splitext(full_path)[1].lower() in [".pdf", ".jpg", ".jpeg", ".png"]:
            print(f"Processing file: {filename}")
            process_file(full_path, api_key)
        else:
            print(f"Skipping {filename}, unsupported file type or directory.")

if __name__ == "__main__":
    api_key = "api_key"
    folder_path = "pdfs"
    process_folder(folder_path, api_key)
