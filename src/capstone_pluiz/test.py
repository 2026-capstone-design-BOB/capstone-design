import google.generativeai as genai
import os

genai.configure(api_key="AIzaSyAi2Zgu5UgGrcGSefp7s-EQRn3D_gyUd80")

print("--- 사용 가능한 모델 목록 ---")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)