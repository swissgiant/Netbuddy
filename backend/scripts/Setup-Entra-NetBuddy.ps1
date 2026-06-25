<#
.SYNOPSIS
    Richtet die Entra-ID-(Azure-AD-)Seite für NetBuddy-SSO ein — idempotent.

.DESCRIPTION
    Legt an / aktualisiert:
      1. App-Registrierung (Single-Tenant, Web-Plattform) mit Redirect-URI
         https://<host>/auth/callback und Logout-URL.
      2. groupMembershipClaims = "SecurityGroup" (Gruppen kommen in den ID-Token).
      3. Microsoft Graph "User.Read" (delegiert) — für den Overage-Fallback
         (User in >~200 Gruppen → kein groups-Claim → transitiveMemberOf via Graph).
      4. Drei Sicherheitsgruppen für die drei NetBuddy-Rollen (viewer/operator/admin).
      5. Ein Client-Secret.
    Gibt am Ende ALLE Werte aus, die in der NetBuddy-Admin-Seite einzutragen sind.

    Erfordert Admin-Consent für die Graph-Berechtigung (Schalter -GrantAdminConsent,
    benötigt Privileged Role Administrator / Application Administrator).

.NOTES
    Projektneutral: nur -AppName / -RedirectHost / Gruppennamen anpassen.
    Modul: Microsoft.Graph (PowerShell SDK).  Install-Module Microsoft.Graph -Scope CurrentUser

.EXAMPLE
    ./Setup-Entra-NetBuddy.ps1 -RedirectHost bls-srv-netbuddy.bls.local -GrantAdminConsent
#>
[CmdletBinding()]
param(
    [string]$AppName        = "NetBuddy",
    [Parameter(Mandatory)] [string]$RedirectHost,          # FQDN, HTTPS, KEINE nackte IP
    # BLS-Namenscodex: G_Netbuddy_<Rolle>. Owner = admin (höchste Rolle).
    [string]$AdminGroup     = "G_Netbuddy_Owner",          # -> NetBuddy-Rolle "admin"
    [string]$OperatorGroup  = "G_Netbuddy_Operator",       # -> NetBuddy-Rolle "operator"
    [string]$ViewerGroup    = "G_Netbuddy_Viewer",         # -> NetBuddy-Rolle "viewer"
    [switch]$GrantAdminConsent
)

$ErrorActionPreference = "Stop"

$RedirectUri = "https://$RedirectHost/auth/callback"
$LogoutUri   = "https://$RedirectHost/"

Write-Host "== Verbinde mit Microsoft Graph ==" -ForegroundColor Cyan
Connect-MgGraph -Scopes "Application.ReadWrite.All","Group.ReadWrite.All","Directory.ReadWrite.All" | Out-Null
$ctx      = Get-MgContext
$tenantId = $ctx.TenantId
Write-Host "Tenant: $tenantId"

# --- 1) App-Registrierung (idempotent über DisplayName) -------------------------------------
Write-Host "`n== App-Registrierung '$AppName' ==" -ForegroundColor Cyan
$app = Get-MgApplication -Filter "displayName eq '$AppName'" -ConsistencyLevel eventual -All | Select-Object -First 1

# Microsoft Graph App-ID + delegierte Permission User.Read
$graphAppId      = "00000003-0000-0000-c000-000000000000"
$userReadScopeId = "e1fe6dd8-ba31-4d61-89e7-88639da4683d"   # User.Read (delegated)
$requiredAccess  = @{
    ResourceAppId  = $graphAppId
    ResourceAccess = @(@{ Id = $userReadScopeId; Type = "Scope" })
}
$webConfig = @{
    RedirectUris          = @($RedirectUri)
    LogoutUrl             = $LogoutUri
    ImplicitGrantSettings = @{ EnableIdTokenIssuance = $false; EnableAccessTokenIssuance = $false }
}

if (-not $app) {
    $app = New-MgApplication -DisplayName $AppName `
        -SignInAudience "AzureADMyOrg" `
        -Web $webConfig `
        -GroupMembershipClaims "SecurityGroup" `
        -RequiredResourceAccess @($requiredAccess)
    Write-Host "App neu angelegt."
} else {
    Update-MgApplication -ApplicationId $app.Id `
        -Web $webConfig `
        -GroupMembershipClaims "SecurityGroup" `
        -RequiredResourceAccess @($requiredAccess)
    Write-Host "App aktualisiert (Redirect/Claims/Permissions)."
}
$app = Get-MgApplication -ApplicationId $app.Id
$clientId = $app.AppId

# Service Principal sicherstellen (für Consent + Gruppen-Zuweisung im Enterprise-App-Kontext)
$sp = Get-MgServicePrincipal -Filter "appId eq '$clientId'" -All | Select-Object -First 1
if (-not $sp) { $sp = New-MgServicePrincipal -AppId $clientId; Write-Host "Service Principal angelegt." }

# --- 2) Drei Sicherheitsgruppen (idempotent) ------------------------------------------------
function Ensure-Group([string]$name) {
    $g = Get-MgGroup -Filter "displayName eq '$name'" -ConsistencyLevel eventual -All | Select-Object -First 1
    if (-not $g) {
        $mailNick = ($name -replace '[^a-zA-Z0-9]', '')
        $g = New-MgGroup -DisplayName $name -MailEnabled:$false -MailNickname $mailNick `
                         -SecurityEnabled:$true -GroupTypes @()
        Write-Host "Gruppe '$name' angelegt."
    } else {
        Write-Host "Gruppe '$name' existiert."
    }
    return $g
}
Write-Host "`n== Sicherheitsgruppen (Rollen) ==" -ForegroundColor Cyan
$gViewer   = Ensure-Group $ViewerGroup
$gOperator = Ensure-Group $OperatorGroup
$gAdmin    = Ensure-Group $AdminGroup

# --- 3) Client-Secret -----------------------------------------------------------------------
Write-Host "`n== Client-Secret ==" -ForegroundColor Cyan
$secret = Add-MgApplicationPassword -ApplicationId $app.Id -PasswordCredential @{
    DisplayName = "netbuddy-sso-$(Get-Date -Format yyyyMMdd)"
    EndDateTime = (Get-Date).AddYears(2)
}
Write-Host "Neues Secret erzeugt (gilt 2 Jahre). NUR JETZT sichtbar — sofort notieren!"

# --- 4) Admin-Consent (optional) ------------------------------------------------------------
if ($GrantAdminConsent) {
    Write-Host "`n== Admin-Consent für Graph User.Read ==" -ForegroundColor Cyan
    $graphSp = Get-MgServicePrincipal -Filter "appId eq '$graphAppId'" -All | Select-Object -First 1
    $existing = Get-MgOauth2PermissionGrant -All | Where-Object {
        $_.ClientId -eq $sp.Id -and $_.ResourceId -eq $graphSp.Id
    } | Select-Object -First 1
    if ($existing) {
        Update-MgOauth2PermissionGrant -OAuth2PermissionGrantId $existing.Id -Scope "User.Read"
    } else {
        New-MgOauth2PermissionGrant -ClientId $sp.Id -ConsentType "AllPrincipals" `
            -ResourceId $graphSp.Id -Scope "User.Read" | Out-Null
    }
    Write-Host "Admin-Consent erteilt."
} else {
    Write-Host "`nHinweis: Admin-Consent NICHT erteilt. Mit -GrantAdminConsent erneut ausfuehren," -ForegroundColor Yellow
    Write-Host "oder im Portal: Enterprise Applications > $AppName > Permissions > Grant admin consent." -ForegroundColor Yellow
}

# --- 5) Ausgabe der NetBuddy-Werte ----------------------------------------------------------
Write-Host "`n=================== In die NetBuddy-Admin-Seite eintragen ===================" -ForegroundColor Green
[PSCustomObject]@{
    "Tenant ID"            = $tenantId
    "Client ID"            = $clientId
    "Client Secret"        = $secret.SecretText
    "Redirect URI"         = $RedirectUri
    "Group ID (Viewer)"    = $gViewer.Id
    "Group ID (Operator)"  = $gOperator.Id
    "Group ID (Admin)"     = $gAdmin.Id
} | Format-List
Write-Host "============================================================================" -ForegroundColor Green
Write-Host "Mitglieder den Gruppen '$ViewerGroup' / '$OperatorGroup' / '$AdminGroup' zuweisen." -ForegroundColor Green
Write-Host "Secret ist NUR HIER sichtbar — jetzt in NetBuddy speichern." -ForegroundColor Yellow
