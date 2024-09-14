import os
import subprocess
import fitz  # type: ignore # PyMuPDF
from PyPDF2 import PdfReader, PdfWriter
from PIL import Image
import shutil
import PIL
import warnings
import PyPDF2
from PIL import Image, ImageEnhance
import io
# Increase the threshold or suppress the warning entirely
Image.MAX_IMAGE_PIXELS = None  # Disables the check completely
warnings.simplefilter('ignore', Image.DecompressionBombWarning)

PIL.Image.MAX_IMAGE_PIXELS = 933120000  # Disable DecompressionBombWarning

ghost_script = rf"gs"

def check_pdf_producer(pdf_path, producer_strings=["TCPDF", "ReportLab", "GPL"]):
    try:
        with open(pdf_path, 'rb') as file:
            reader = PdfReader(file)
            metadata = reader.metadata
            
            if metadata is None:
                return False
            
            producer = metadata.get('/Producer', '')
            if any(ps in producer for ps in producer_strings):
                num_pages = len(reader.pages)
                return num_pages >= 5
            
            return False
    except Exception as e:
        print(f"Error processing {pdf_path}: {e}")
        return False

def convert_pdf_to_images(pdf_path, output_folder, zoom=5.0, color_quality=100, bw_quality=50, max_dim=2000):
    print("CONVERTING PDF TO IMAGE")
    doc = fitz.open(pdf_path)
    os.makedirs(output_folder, exist_ok=True)
    
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        
        # Convert Pixmap to PIL Image
        img = Image.open(io.BytesIO(pix.tobytes()))
        
        # Resize image if dimensions exceed max_dim
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        
        # Process color images with higher quality
        if img.mode == 'RGB':
            img.save(os.path.join(output_folder, f"{page_num + 1}.jpeg"), "JPEG", quality=color_quality)
        else:
            # Convert BW images to grayscale, lower the quality, and optimize
            img = img.convert('L')
            img.save(os.path.join(output_folder, f"{page_num + 1}.jpeg"), "JPEG", quality=bw_quality, optimize=True)
    
    doc.close()

def convert_images_to_pdf(image_folder, output_pdf_path):
    print("CONVERTING IMAGES TO PDF")
    doc = fitz.open()
    image_files = sorted(os.listdir(image_folder), key=lambda x: int(x.split('.')[0]))
    for image_file in image_files:
        image_path = os.path.join(image_folder, image_file)
        img = fitz.open(image_path)
        rect = img[0].rect
        pdfbytes = img.convert_to_pdf()
        img_pdf = fitz.open("pdf", pdfbytes)
        page = doc.new_page(width=rect.width, height=rect.height)
        page.show_pdf_page(rect, img_pdf, 0)
    doc.save(output_pdf_path)
    doc.close()

def split_pdf(pdf_path, chunk_size=10, temp_folder=None):
    """ Split PDF into chunks of `chunk_size` pages each. """
    print("MAKING CHUNKS OF PDF FOR FASTER OCR PROCESSING")
    doc = fitz.open(pdf_path)
    num_pages = len(doc)
    chunk_paths = []
    for start in range(0, num_pages, chunk_size):
        end = min(start + chunk_size, num_pages)
        chunk_doc = fitz.open()
        for page_num in range(start, end):
            chunk_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        chunk_path = os.path.join(temp_folder, f"chunk_{start//chunk_size + 1}.pdf")
        chunk_doc.save(chunk_path)
        chunk_doc.close()
        chunk_paths.append(chunk_path)
    doc.close()
    return chunk_paths

def combine_pdfs(pdf_paths, output_pdf_path):
    """ Combine multiple PDFs into one. """
    print("COMBINING CHUNKS OF PDF INTO ONE")
    pdf_writer = PdfWriter()
    for pdf_path in pdf_paths:
        pdf_reader = PdfReader(pdf_path)
        for page in pdf_reader.pages:
            pdf_writer.add_page(page)
    with open(output_pdf_path, 'wb') as out_file:
        pdf_writer.write(out_file)

def convert_pdf_to_ocr(source_file, destination_file):
    print("MAKE OCR")
    """ Convert a PDF to an OCR-processed PDF. """
    try:
        ocr_command = f'ocrmypdf "{source_file}" "{destination_file}" -l eng+hin -O 3 --redo-ocr --clean --jobs 4 --output-type pdf'
        subprocess.run(ocr_command, shell=True, check=True)
    except Exception as e:
        print(f"Error processing {source_file}: {e}")

def compatible_1_4(input_pdf, output_pdf, image_downsampling="Bicubic", image_resolution=300, embed_fonts=False):
    print("MAKING THE PDF COMPATIBLE FOR SERVER UPLOAD")
    """ Compress PDF to ensure compatibility with PDF 1.4. """
    command = [
        ghost_script,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dNOPAUSE",
        "-dBATCH",
        "-dQUIET",
        f"-dColorImageDownsampleType=/{image_downsampling}",
        f"-dColorImageResolution={image_resolution}",
        f"-dGrayImageDownsampleType=/{image_downsampling}",
        f"-dGrayImageResolution={image_resolution}",
        f"-dMonoImageDownsampleType=/{image_downsampling}",
        f"-dMonoImageResolution={image_resolution}",
        "-dAutoRotatePages=/None",  # Prevent automatic rotation
        "-sOutputFile=" + output_pdf,
    ]

    if not embed_fonts:
        command.append("-dEmbedAllFonts=false")

    subprocess.run(command + [input_pdf], check=True)

def attach_bookmarks_to_pdf(source_pdf_path, dest_pdf_path):
    print("ATTACHING BOOKMARKS TO THE PDF")

    # Open the source PDF and destination PDF
    with open(source_pdf_path, 'rb') as source_pdf_file, open(dest_pdf_path, 'rb') as dest_pdf_file:
        source_pdf = PdfReader(source_pdf_file)
        dest_pdf = PdfReader(dest_pdf_file)
        dest_pdf_writer = PdfWriter()

        # Copy all pages from the destination PDF to the writer
        for page in dest_pdf.pages:
            dest_pdf_writer.add_page(page)

        # Define a function to add bookmarks recursively
        def add_bookmarks(outlines, parent=None):
            for outline in outlines:
                if isinstance(outline, list):
                    add_bookmarks(outline, parent)
                else:
                    title = outline.title
                    # Obtain the correct page number from the source PDF
                    page_index = source_pdf.get_page_number(outline.page)
                    dest_pdf_writer.add_outline_item(title, page_index, parent)

        # Add bookmarks from the source PDF to the destination PDF
        if source_pdf.outline:
            add_bookmarks(source_pdf.outline)
        else:
            # Add a default bookmark if none exist in the source
            dest_pdf_writer.add_outline_item("No Bookmarks", 0)

        # Write the updated PDF with the bookmarks to the destination path
        with open(dest_pdf_path, 'wb') as output_pdf_file:
            dest_pdf_writer.write(output_pdf_file)

def process_pdfs_in_folder(source_folder, destination_folder, producer_strings=["TCPDF", "ReportLab", "GPL"]):
    for root, _, files in os.walk(source_folder):
        relative_path = os.path.relpath(root, source_folder)
        output_dir = os.path.join(destination_folder, relative_path)

        os.makedirs(output_dir, exist_ok=True)

        for filename in files:
            if filename.endswith(".pdf"):
                pdf_path = os.path.join(root, filename)
                output_pdf_path = os.path.join(output_dir, filename)

                if os.path.exists(output_pdf_path):
                    print(f"{output_pdf_path} exists in destination folder, skipping.")
                    continue

                if check_pdf_producer(pdf_path, producer_strings):
                    temp_dir = os.path.join(output_dir, "temp_processing")
                    os.makedirs(temp_dir, exist_ok=True)

                    image_output_folder = os.path.join(temp_dir, "images")
                    os.makedirs(image_output_folder, exist_ok=True)

                    # Convert PDF to images
                    convert_pdf_to_images(pdf_path, image_output_folder)
                    # Convert images back to PDF
                    temp_pdf_path = os.path.join(temp_dir, "reconverted.pdf")
                    convert_images_to_pdf(image_output_folder, temp_pdf_path)

                    # Split the PDF into chunks
                    chunk_paths = split_pdf(temp_pdf_path, temp_folder=temp_dir)
                    ocr_chunk_paths = []
                    for chunk_path in chunk_paths:
                        chunk_output_path = os.path.join(temp_dir, f"ocr_{os.path.basename(chunk_path)}")
                        convert_pdf_to_ocr(chunk_path, chunk_output_path)
                        ocr_chunk_paths.append(chunk_output_path)

                    # Combine OCR processed chunks
                    combined_pdf_path = os.path.join(temp_dir, "combined.pdf")
                    combine_pdfs(ocr_chunk_paths, combined_pdf_path)

                    # Attach bookmarks to the combined PDF
                    attach_bookmarks_to_pdf(pdf_path, combined_pdf_path)

                    # Make compatible with PDF 1.4
                    compatible_pdf_path = output_pdf_path
                    compatible_1_4(combined_pdf_path, compatible_pdf_path)

                    # Clean up temporary files
                    shutil.rmtree(temp_dir)

                else:
                    ocr_output_folder = os.path.join(output_dir, "ocr_processing")
                    os.makedirs(ocr_output_folder, exist_ok=True)
                    ocr_pdf_path = os.path.join(ocr_output_folder, filename)
                    convert_pdf_to_ocr(pdf_path, ocr_pdf_path)
                    compatible_pdf_path = output_pdf_path
                    compatible_1_4(ocr_pdf_path, compatible_pdf_path)
                    os.remove(ocr_pdf_path)
                    shutil.rmtree(ocr_output_folder)

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python script.py <source_folder> <destination_folder>")
    else:
        source_folder = sys.argv[1]
        destination_folder = sys.argv[2]
        process_pdfs_in_folder(source_folder, destination_folder)
