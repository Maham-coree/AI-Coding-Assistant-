document.addEventListener("DOMContentLoaded",function(){
    const form = document.querySelector("form");
    const btn = document.getElementById("askBtn");
    const textarea = document.querySelector("textarea");
    const darkBtn =document.getElementById("darkModeBtn");
    const clearBtn = document.getElementById("clearBtn");
    const response= document.getElementById("response_text");
    loadHistory();
    textarea.focus();
   
   

    form.addEventListener("submit",function(){

const question=
document.querySelector("textarea").value.trim();
if(question===""){

showToast("Please enter your question.");

textarea.focus();

return false;

}

if(question!==""){

saveHistory(question);

}
btn.innerHTML='<span class="spinner"></span> 🤖 Thinking...';
btn.style.opacity="0.8";

btn.disabled=true;

});
textarea.addEventListener("keydown", function(e){

    if(e.key === "Enter" && !e.shiftKey){

        e.preventDefault();

        form.requestSubmit();

    }

});

clearBtn.addEventListener("click",function(){

    textarea.value="";

    textarea.focus();

});


textarea.addEventListener("keydown", function(event){

    if(event.key === "Enter" && event.ctrlKey){

        event.preventDefault();

        form.requestSubmit();

    }

});


darkBtn.addEventListener("click", function(){

    document.documentElement.classList.toggle("dark-mode");

    if(document.documentElement.classList.contains("dark-mode")){
        localStorage.setItem("theme","dark");
        darkBtn.innerHTML="☀️ Light Mode";
    }else{
        localStorage.setItem("theme","light");
        darkBtn.innerHTML="🌙 Dark Mode";
    }

});
window.addEventListener("pageshow", function(){

    const btn=document.getElementById("askBtn");

    btn.disabled=false;

    btn.innerHTML="Ask AI";

    btn.style.opacity="1";

});
});

let speech;

function speakResponse(){

    const btn=document.getElementById("speakBtn");

    const text=document.getElementById("response_text").innerText;

    speech=new SpeechSynthesisUtterance(text);

    btn.innerHTML="⏹ Stop";

    btn.onclick=stopSpeech;

    speech.onend=function(){

        btn.innerHTML="🔊 Speak";

        btn.onclick=speakResponse;

    }

    window.speechSynthesis.speak(speech);

}

function stopSpeech(){

    window.speechSynthesis.cancel();

    const btn=document.getElementById("speakBtn");

    btn.innerHTML="🔊 Speak";

    btn.onclick=speakResponse;

}
function saveHistory(question){

    let chatHistory = JSON.parse(localStorage.getItem("chatHistory")) || [];

    if(chatHistory.includes(question)){
        return;
    }

    chatHistory.unshift(question);

    chatHistory = chatHistory.slice(0,10);

    localStorage.setItem("chatHistory", JSON.stringify(chatHistory));

    loadHistory();

}





function loadHistory(){

const chatHistory =
JSON.parse(localStorage.getItem("chatHistory")) || [];

const historyList =
document.getElementById("historyList");

historyList.innerHTML="";

if(chatHistory.length===0){

historyList.innerHTML="<p>No chats yet...</p>";

return;

}

chatHistory.forEach(function(item){

const div=document.createElement("div");

div.className="history-item";

div.innerText=item.length>35?
item.substring(0,35)+"...":item;

div.addEventListener("click",function(){

document.querySelector("textarea").value=item;

});

historyList.appendChild(div);

});

}



function clearHistory(){

localStorage.removeItem("chatHistory");

document.getElementById("historyList").innerHTML="<p>No chats yet...</p>";

}

function searchHistory(){

    const value = document.getElementById("searchHistory").value.toLowerCase();

    const items = document.querySelectorAll(".history-item");

    items.forEach(function(item){

        if(item.innerText.toLowerCase().includes(value)){
            item.style.display="block";
        }else{
            item.style.display="none";
        }

    });

}
function showToast(message){

    const toast = document.getElementById("toast");

    toast.innerText = message;

    toast.classList.add("show");

    setTimeout(function(){

        toast.classList.remove("show");

    },2000);

}

function copyText(){

const response=document.getElementById("response_text");

if(!response){
    return;
}

navigator.clipboard.writeText(response.innerText);

showToast("Response Copied Successfully!");

}


const response = document.getElementById("response_text");

if(response){

    response.scrollIntoView({
        behavior:"smooth"
    });

}

const codeBlocks = document.querySelectorAll("pre code");

codeBlocks.forEach(function(block){

    block.removeAttribute("data-highlighted");

    hljs.highlightElement(block);

});
function copyCode(){

    const code =
    document.getElementById("response_text").innerText;

    navigator.clipboard.writeText(code);

    showToast("Code Copied Successfully!");

}
