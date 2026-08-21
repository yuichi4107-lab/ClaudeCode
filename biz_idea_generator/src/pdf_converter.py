import os
import subprocess
import shutil

def convert_to_pdf(markdown_text, output_path):
    """
    Converts markdown text to PDF using Node.js 'md-to-pdf' via npx.
    """
    # Create a temporary markdown file
    temp_md_path = output_path.replace(".pdf", ".temp.md")
    
    try:
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_text)
            
        print(f"Running npx md-to-pdf on {temp_md_path}...")
        
        # Use shell=True for windows npx resolution usually
        # npx -y md-to-pdf input.md --config-file pdf_config.json
        cmd = ["npx", "-y", "md-to-pdf", temp_md_path, "--config-file", "pdf_config.json"]
        
        # Capture output to see errors, handle encoding safely
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
        print("MD-TO-PDF STDOUT:", result.stdout[:200]) # Limit log
        
        # md-to-pdf output: temp.pdf (default behavior is input.pdf next to input.md)
        generated_pdf = temp_md_path.replace(".md", ".pdf")
        
        if os.path.exists(generated_pdf):
            # Move to target output_path (use shutil.move for cross-drive and locked file handling)
            import time
            for attempt in range(3):
                try:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    shutil.move(generated_pdf, output_path)
                    break
                except (PermissionError, OSError):
                    if attempt < 2:
                        time.sleep(1)
                    else:
                        # Fallback: keep generated PDF in place
                        print(f"Could not move to {output_path}, PDF available at {generated_pdf}")
                        return True
            
            # Cleanup temp md
            if os.path.exists(temp_md_path):
                os.remove(temp_md_path)
            return True
        else:
            print("PDF file was not created by md-to-pdf.")
            print("Note: md-to-pdf might have failed silently or output elsewhere.")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"Error running npx: {e}")
        print(f"Stderr: {e.stderr}")
        return False
    except Exception as e:
        print(f"Exception during PDF conversion: {e}")
        return False

if __name__ == "__main__":
    # Test
    sample_text = "# テスト\nこれは日本語のテストです。\n- 項目1\n- 項目2"
    if convert_to_pdf(sample_text, "test.pdf"):
        print("Success: test.pdf created.")
    else:
        print("Failed to create test.pdf")
