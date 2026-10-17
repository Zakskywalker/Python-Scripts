#pip install pypdf

from pathlib import Path
import re
from pypdf import PdfWriter

def extract_leading_number(file_path):
    # Search for a number at the start of the filename
    match = re.match(r"^(\d+)", file_path.name)
    # Return the number as an integer so 10 comes after 2. If no number, default to infinity.
    return int(match.group(1)) if match else float('inf')

def merge_sequential_pdfs(directory_path, output_path):
    target_dir = Path(directory_path)
    
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"Error: The directory '{directory_path}' does not exist.")
        return

    # Find all PDFs in the folder
    all_pdfs = list(target_dir.glob("*.pdf"))
    
    # Sort them sequentially based on their leading number (1, 2, 3...)
    sequential_pdfs = sorted(all_pdfs, key=extract_leading_number)
    
    if not sequential_pdfs:
        print(f"No PDF files found in '{directory_path}'.")
        return

    writer = PdfWriter()
    
    print("--- Starting Sequential Merge ---")
    for pdf_path in sequential_pdfs:
        # Check if the file actually starts with a number to avoid unexpected files
        if extract_leading_number(pdf_path) == float('inf'):
            print(f"Skipping (No leading number found): {pdf_path.name}")
            continue
            
        # Print the title of the PDF being added
        print(f"Combining: {pdf_path.name}")
        writer.append(pdf_path)
        
    # Save the combined file
    with open(output_path, "wb") as output_file:
        writer.write(output_file)
        
    writer.close()
    print("---------------------------------")
    print(f"Success! Output saved to: {output_path}")

# Example usage:
my_folder = r"" 
merge_sequential_pdfs(my_folder, "output.pdf")