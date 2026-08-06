# Run in Google Colab

1. Open Google Colab.
2. Select `Runtime > Change runtime type`.
3. Choose `T4 GPU`.
4. Upload `secure_text_to_image_colab.zip`.

Run:

```python
import os
os.chdir("/content")
print(os.getcwd())
```

```python
from google.colab import files
uploaded = files.upload()
```

```python
!rm -rf /content/secure_text_to_image
!unzip -q /content/secure_text_to_image_colab.zip -d /content/secure_text_to_image
os.chdir("/content/secure_text_to_image")
print(os.listdir())
```

```python
!pip install -r requirements_vscode.txt
```

```python
!python app.py
```

Open the Gradio public link.

Admin login:

```text
Username: admin
Password: Gnk2005/09-07
```
