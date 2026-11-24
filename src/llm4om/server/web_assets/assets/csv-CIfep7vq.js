function e(e,t=`,`){let n=e=>{let n=e==null?``:e instanceof Date?e.toISOString().replace(/T00:00:00\.000Z$/,``).replace(/\.000Z$/,`Z`):String(e);return/["\n\r]/.test(n)||n.includes(t)?`"${n.replace(/"/g,`""`)}"`:n};return e.map(e=>e.map(n).join(t)).join(`
`)+`
`}function t(e,t=`,`){let n=e.replace(/^\uFEFF/,``),r=[],i=[],a=``,o=!1,s=!1;for(let e=0;e<n.length;e++){let c=n[e];if(o)c===`"`&&n[e+1]===`"`?(a+=`"`,e++):c===`"`?(o=!1,s=!0):a+=c;else if(c===t)i.push(a),a=``,s=!1;else if(c===`
`||c===`\r`)c===`\r`&&n[e+1]===`
`&&e++,i.push(a),r.push(i),i=[],a=``,s=!1;else if(c===`"`&&!a&&!s)o=!0;else if(c===`"`||s)throw Error(`Unexpected text outside a quoted field.`);else a+=c}if(o)throw Error(`Unclosed quoted field.`);return(a||i.length||s)&&(i.push(a),r.push(i)),r}export{e as n,t};