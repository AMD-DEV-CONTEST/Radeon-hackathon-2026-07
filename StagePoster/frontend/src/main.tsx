import {StrictMode} from 'react';import{createRoot}from'react-dom/client';import{BrowserRouter}from'react-router-dom';import App from'./App';import{StoreProvider}from'./store';import'./styles/global.css';
createRoot(document.getElementById('root')!).render(<StrictMode><BrowserRouter><StoreProvider><App/></StoreProvider></BrowserRouter></StrictMode>);
