import {cpSync,mkdirSync} from "node:fs";
mkdirSync("public/pdfjs",{recursive:true});
cpSync("node_modules/pdfjs-dist/LICENSE","public/pdfjs/LICENSE");
for (const folder of ["cmaps","standard_fonts","wasm"]) {
  mkdirSync(`public/pdfjs/${folder}`,{recursive:true});
  cpSync(`node_modules/pdfjs-dist/${folder}`,`public/pdfjs/${folder}`,{recursive:true});
}

