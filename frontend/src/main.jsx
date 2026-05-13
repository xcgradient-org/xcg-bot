import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles/shared.css";
import "./styles/meeting-creator.css";
import "./styles/claude-usage.css";

createRoot(document.getElementById("root")).render(<App />);
