import { BrowserRouter, Route, Routes } from "react-router-dom";
import { MotionConfig } from "framer-motion";
import SiteLayout from "./components/site/SiteLayout";
import Landing from "./pages/Landing";
import Product from "./pages/Product";
import HowItWorks from "./pages/HowItWorks";
import ModelTrust from "./pages/ModelTrust";
import Resources from "./pages/Resources";
import AppPlaceholder from "./pages/AppPlaceholder";

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <Routes>
          <Route element={<SiteLayout />}>
            <Route path="/" element={<Landing />} />
            <Route path="/product" element={<Product />} />
            <Route path="/how-it-works" element={<HowItWorks />} />
            <Route path="/model-trust" element={<ModelTrust />} />
            <Route path="/resources" element={<Resources />} />
          </Route>
          <Route path="/app/*" element={<AppPlaceholder />} />
        </Routes>
      </BrowserRouter>
    </MotionConfig>
  );
}
