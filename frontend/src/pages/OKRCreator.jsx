import LegacyToolPage from "./LegacyToolPage.jsx";
import okrHtml from "../legacy/okr-creator.html?raw";

export default function OKRCreator() {
  return <LegacyToolPage html={okrHtml} title="XC Gradient — OKR Creator" subtitle="OKR Creator" />;
}
