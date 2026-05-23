import google.generativeai as genai
import os

genai.configure(api_key="여러분의_API_키")

print("--- 사용 가능한 모델 목록 ---")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)