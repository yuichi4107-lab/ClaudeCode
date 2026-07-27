import requests
import zipfile
import io

url = "https://moji.or.jp/wp-content/ipafont/IPAexfont/IPAexfont00401.zip"
print(f"Downloading font zip from {url}...")
try:
    r = requests.get(url)
    r.raise_for_status()
    
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        # Loop to find ipaexg.ttf
        for name in z.namelist():
            if name.endswith("ipaexg.ttf"):
                print(f"Extracting {name} to src/font.ttf...")
                with z.open(name) as source, open("src/font.ttf", "wb") as target:
                    target.write(source.read())
                break
    print("Font downloaded and extracted to src/font.ttf")
except Exception as e:
    print(f"Error downloading font: {e}")
