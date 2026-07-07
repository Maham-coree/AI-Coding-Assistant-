from flask import Flask , render_template , request
import os 
from dotenv import load_dotenv
from google import genai  
load_dotenv()
api_key=os.getenv("GEMINI_API_KEY")
client= genai.Client(api_key=api_key)
app= Flask(__name__)
@app.route("/")
def home():
    return render_template("index.html")
@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.form["user_input"]
    prompt = F"""
    Answer Shortly.
    Maximum 10-15 lines.
    Question:{user_input}
    """
    try: 
       response = client.models.generate_content(
           model="gemini-2.5-flash",
           contents=f"""
        You are an  expert AI Coding Assisstant.
        Rules:
        -Answer in Simple English.
        -explain with concept in 10-15 lines.
        -If code is needed, provide code.
        -Explain step by step.
        -Use bullet points where helpful.
        Question:
        {user_input}
        """
       )
       ai_response = response.text
    except Exception as e: 
        ai_response = f"Error: {e}"
    return render_template(
        "index.html",
        ai_response=ai_response,
         user_input=user_input) 
if __name__=="__main__":
    app.run(debug=True) 