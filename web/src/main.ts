import { initializeLocale } from "./i18n/runtime";
import "./styles/index.css";
import { mount } from "svelte";
import App from "./App.svelte";

initializeLocale();

const target = document.querySelector<HTMLDivElement>("#app");
if (!target) throw new Error("Ponto de montagem ausente");
mount(App, { target });
