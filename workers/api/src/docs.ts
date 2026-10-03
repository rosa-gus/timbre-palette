// Pin browser assets so a CDN release cannot silently change the documentation UI.
const SWAGGER_UI_ASSETS = "https://unpkg.com/swagger-ui-dist@5.33.1";

export function apiDocs(): Response {
  return new Response(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Timbre Palette API / Documentation</title>
    <link rel="stylesheet" href="${SWAGGER_UI_ASSETS}/swagger-ui.css">
  </head>
  <body>
    <noscript>Enable JavaScript to view the documentation, or <a href="/openapi.json">open the OpenAPI document</a>.</noscript>
    <div id="swagger-ui"></div>
    <script src="${SWAGGER_UI_ASSETS}/swagger-ui-bundle.js" crossorigin="anonymous"></script>
    <script>
      SwaggerUIBundle({
        url: "/openapi.json",
        dom_id: "#swagger-ui",
        deepLinking: true,
        validatorUrl: null,
        presets: [SwaggerUIBundle.presets.apis],
        layout: "BaseLayout"
      });
    </script>
  </body>
</html>`, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
  });
}
