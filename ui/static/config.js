// Backend base URL for Galen's API.
// Leave empty to use the same origin (e.g. local `uvicorn`/Docker), or set
// this to the hosted backend (AWS API Gateway) when served from a static CDN
// such as Vercel.
window.GALEN_API_BASE = "https://3strtwnmd0.execute-api.us-east-1.amazonaws.com/prod";

function galenApi(path) {
  return (window.GALEN_API_BASE || "") + path;
}