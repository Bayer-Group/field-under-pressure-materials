/**
 * [PLACEHOLDER BARREL]
 *
 * All temporary UI placeholder data lives inside `src/placeholders/`.
 * To remove placeholders once the backend is connected:
 *   1. Set `VITE_USE_PLACEHOLDERS=false` in `ui/.env`
 *   2. Delete this `src/placeholders/` directory
 *   3. Remove the single placeholder import and fallback branches in `src/api/orchardApi.ts`
 */

export { getPlaceholderTemperatureSeries } from './temperaturePlaceholder';
export { getPlaceholderOrchardHealth, getPlaceholderOrchardScene } from './orchard3dPlaceholder';
export {
  getPlaceholderCropPrefs,
  getPlaceholderOrchardBoundary,
  getPlaceholderSaveOrchardLayoutResponse,
} from './rowEditorPlaceholder';
