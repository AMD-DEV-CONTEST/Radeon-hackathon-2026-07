function sendMessage(){

let input=document.getElementById("userInput");

let message=input.value;


if(message===""){
    return;
}


let chatBox=document.getElementById("chatBox");


// User message

chatBox.innerHTML +=
`
<div class="user-message">
${message}
</div>
`;



// Simple AI response (temporary)

let reply="I recommend consulting your healthcare provider for personalized medical advice.";


if(message.toLowerCase().includes("food")){

reply="Include fruits, vegetables, protein-rich foods and iron-rich foods during pregnancy.";

}


else if(message.toLowerCase().includes("exercise")){

reply="Light exercises like walking can be helpful during pregnancy if approved by your doctor.";

}


else if(message.toLowerCase().includes("sleep")){

reply="Try maintaining a regular sleep schedule and get adequate rest.";

}



chatBox.innerHTML +=
`
<div class="bot-message">
👩‍⚕️ ${reply}
</div>
`;



input.value="";

chatBox.scrollTop=chatBox.scrollHeight;

}