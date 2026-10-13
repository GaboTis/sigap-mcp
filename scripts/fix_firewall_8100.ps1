# Abre el puerto 8100 en el Firewall de Windows para sigap-mcp (API + dashboard + MCP HTTP).
# Regla limitada al uvicorn.exe del venv. Requiere ejecutarse como Administrador.
$log = 'C:\Users\User\Documents\CODE\sigap-mcp\logs\firewall_8100.log'
$program = 'C:\Users\User\Documents\CODE\sigap-mcp\venv\Scripts\uvicorn.exe'

try {
    Remove-NetFirewallRule -DisplayName 'SIGAP Data (TCP 8100)' -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName 'SIGAP Data (TCP 8100)' `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8100 `
        -Program $program -Profile Any `
        -Description 'sigap-mcp: API de datos SIGAP con token (dashboard ejecutivo, MCP HTTP)' | Out-Null
    "OK: regla creada $(Get-Date) | program=$program | port=8100 | profiles=Any" | Out-File $log -Encoding utf8
} catch {
    "ERROR: $($_.Exception.Message)" | Out-File $log -Encoding utf8
}
