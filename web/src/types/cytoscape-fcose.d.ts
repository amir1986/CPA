/**
 * Minimal type shim for cytoscape-fcose — no @types package on npm.
 * The library exports a default Cytoscape extension function:
 *   import fcose from "cytoscape-fcose";
 *   cytoscape.use(fcose);
 */
declare module "cytoscape-fcose" {
  import type { Ext } from "cytoscape";
  const fcose: Ext;
  export default fcose;
}
