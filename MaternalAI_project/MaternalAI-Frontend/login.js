function showRegister(){

    document.getElementById("loginForm").style.display="none";

    document.getElementById("registerForm").style.display="block";
}

function showLogin(){

    document.getElementById("registerForm").style.display="none";

    document.getElementById("loginForm").style.display="block";
}

// REGISTER

function register(){

    const user={

        name:document.getElementById("name").value,

        email:document.getElementById("email").value,

        password:document.getElementById("password").value
    };

    fetch(
        "http://localhost:8080/api/users/register",
        {

            method:"POST",

            headers:{
                "Content-Type":"application/json"
            },

            body:JSON.stringify(user)
        }
    )

    .then(res=>res.text())

    .then(msg=>{

        document.getElementById("msg").innerText=msg;

        showLogin();
    })

    .catch(err=>{

        document.getElementById("msg").innerText=
        "Registration Failed";
    });
}


// LOGIN

function login(){

    const user={

        email:document.getElementById("loginEmail").value,

        password:document.getElementById("loginPassword").value
    };

    fetch(
        "http://localhost:8080/api/users/login",
        {

            method:"POST",

            headers:{
                "Content-Type":"application/json"
            },

            body:JSON.stringify(user)
        }
    )

    .then(res=>{

        if(!res.ok){

            throw new Error(
                "Invalid Credentials"
            );
        }

        return res.text();
    })

    .then(msg=>{

        document.getElementById("msg").innerText=msg;

        setTimeout(()=>{

            window.location.href=
            "dashboard.html";

        },1000);
    })

    .catch(err=>{

        document.getElementById("msg").innerText=
        err.message;
    });
}