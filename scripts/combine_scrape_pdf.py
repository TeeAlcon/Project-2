import pymupdf


def combine_saved_pdfs(pdf_files, output_path, delete_originals=True):
    if not pdf_files:
        print("No PDFs were provided to combine.")
        return None

    combined_doc = pymupdf.open()
    valid_pdf_count = 0
    files_to_delete = []

    for i, pdf_file in enumerate(pdf_files, start=1):
        try:
            print(f"Inserting PDF {i}: {pdf_file.name}")

            with pymupdf.open(pdf_file) as src_doc:
                combined_doc.insert_pdf(src_doc)

            valid_pdf_count += 1
            files_to_delete.append(pdf_file)

        except Exception as e:
            print(f"Skipping bad PDF: {pdf_file.name}")

    if valid_pdf_count == 0:
        combined_doc.close()
        return None

    combined_doc.save(output_path)
    combined_doc.close()

    print(f"Combined PDF saved: {output_path}")

    # ✅ Delete originals after successful combine
    if delete_originals:
        for pdf_file in files_to_delete:
            try:
                pdf_file.unlink()
            except Exception as e:
                print(f"Could not delete {pdf_file.name}")

    return output_path
