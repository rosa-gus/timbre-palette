import { initializeLocale } from "./i18n/runtime";
import App from "./App.svelte";
import "./styles.css";
import { mount } from "svelte";



const target = document.querySelector<HTMLDivElement>("#app");
if (!target) throw new Error("Ponto de montagem ausente");
void initializeLocale().then(() => mount(App, { target }));
