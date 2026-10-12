import { createRoot } from "react-dom/client";
import App from "./App";
import { installUiFacade } from "./facade";
import "./style.css";

installUiFacade();
createRoot(document.getElementById("root")!).render(<App />);
