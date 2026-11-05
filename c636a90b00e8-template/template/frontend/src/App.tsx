import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Home } from "./features/train-ticket-booking-demo/pages/Home";
import { Registration } from "./features/train-ticket-booking-demo/pages/Registration";

export type AppState = {  };

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/register" element={<Registration />} />
        <Route path="*" element={<Home />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
