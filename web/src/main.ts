import "./styles/index.css";
import { mount } from "svelte";
import App from "./App.svelte";

const target = document.querySelector<HTMLDivElement>("#app");
if (!target) throw new Error("Ponto de montagem ausente");
mount(App, { target });
