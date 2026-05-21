import os
from dotenv import load_dotenv
from google import genai  # 1. 라이브러리 임포트

<<<<<<< Updated upstream
genai.configure(api_key="AIzaSyAi2Zgu5UgGrcGSefp7s-EQRn3D_gyUd80")
=======
load_dotenv()
>>>>>>> Stashed changes

# 2. 클라이언트 초기화 (genai 정의)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 사용 예시
response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents='안녕 Gemini?',
)
print(response.text)