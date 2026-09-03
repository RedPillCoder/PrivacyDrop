; ===========================================================================
; PrivacyDrop — NSIS installer script
;
; Build (Windows):
;   makensis installer.nsi
;
; Produces:  dist\PrivacyDrop-1.1.0-Setup.exe
;
; Requires: NSIS 3.x with the Modern UI 2 (MUI2) plug-in (ships with NSIS).
; ===========================================================================

!define APP_NAME        "PrivacyDrop"
!define APP_VERSION     "1.1.0"
!define APP_PUBLISHER   "PrivacyDrop"
!define APP_URL         "https://github.com/privacypdrop/privacypdrop"
!define APP_EXE         "PrivacyDrop.exe"
!define APP_REGKEY      "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

!define MUI_ABORTWARNING
!define MUI_ICON          "assets\icon.ico"
!define MUI_UNICON        "assets\icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP   ""
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP         ""
!define MUI_HEADERIMAGE_RIGHT
!define MUI_LICENSEPAGE_TEXT_TOP       "Read the licence below — then accept to continue."
!define MUI_LICENSEPAGE_BUTTON         "I accept"
!define MUI_FINISHPAGE_RUN             "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT        "Launch ${APP_NAME} now"
!define MUI_FINISHPAGE_LINK            "Visit ${APP_NAME} on GitHub"
!define MUI_FINISHPAGE_LINK_LOCATION   "${APP_URL}"

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"

; ---- General settings ----------------------------------------------------
Name            "${APP_NAME} ${APP_VERSION}"
OutFile         "dist\${APP_NAME}-${APP_VERSION}-Setup.exe"
InstallDir      "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "${APP_REGKEY}" ""
RequestExecutionLevel admin
SetCompressor   /SOLID lzma

; ---- Pages ---------------------------------------------------------------
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE     "LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

; ---- Installer version info ----------------------------------------------
VIProductVersion  "${APP_VERSION}.0"
VIAddVersionKey   "ProductName"     "${APP_NAME}"
VIAddVersionKey   "CompanyName"     "${APP_PUBLISHER}"
VIAddVersionKey   "LegalCopyright"  "Copyright (c) 2026 ${APP_PUBLISHER}"
VIAddVersionKey   "FileDescription" "${APP_NAME} installer"
VIAddVersionKey   "FileVersion"     "${APP_VERSION}"
VIAddVersionKey   "ProductVersion"  "${APP_VERSION}"

; ---- Variables -----------------------------------------------------------
Var DesktopShortcut
Var StartMenuShortcut

; ---- Sections ------------------------------------------------------------
Section "${APP_NAME} (required)" SecCore
    SectionIn RO

    SetOutPath "$INSTDIR"
    File "dist\${APP_EXE}"
    File "LICENSE"
    File "README.md"
    File "CHANGELOG.md"

    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0

    WriteRegStr   HKLM "${APP_REGKEY}" "DisplayName"     "${APP_NAME}"
    WriteRegStr   HKLM "${APP_REGKEY}" "Publisher"       "${APP_PUBLISHER}"
    WriteRegStr   HKLM "${APP_REGKEY}" "DisplayVersion"  "${APP_VERSION}"
    WriteRegStr   HKLM "${APP_REGKEY}" "InstallLocation" "$INSTDIR"
    WriteRegStr   HKLM "${APP_REGKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr   HKLM "${APP_REGKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
    WriteRegDWORD HKLM "${APP_REGKEY}" "NoModify"        1
    WriteRegDWORD HKLM "${APP_REGKEY}" "NoRepair"        1
    WriteRegDWORD HKLM "${APP_REGKEY}" "EstimatedSize"   $0

    WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Desktop shortcut" SecDesktop
    CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" \
                   "$INSTDIR\assets\icon.ico" 0
SectionEnd

Section "Start Menu folder" SecStartMenu
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortCut  "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" \
                    "$INSTDIR\${APP_EXE}" "" \
                    "$INSTDIR\assets\icon.ico" 0
    CreateShortCut  "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk" \
                    "$INSTDIR\Uninstall.exe"
SectionEnd

; ---- Descriptions --------------------------------------------------------
LangString DESC_SecCore     ${LANG_ENGLISH} "${APP_NAME} executable and docs."
LangString DESC_SecDesktop  ${LANG_ENGLISH} "Add a ${APP_NAME} icon to your desktop."
LangString DESC_SecStartMenu ${LANG_ENGLISH} "Add a ${APP_NAME} folder to the Start Menu."

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SecCore}     "${DESC_SecCore}"
    !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop}  "${DESC_SecDesktop}"
    !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} "${DESC_SecStartMenu}"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ---- Uninstaller ---------------------------------------------------------
Section "Uninstall"
    DeleteRegKey HKLM "${APP_REGKEY}"

    Delete "$INSTDIR\${APP_EXE}"
    Delete "$INSTDIR\Uninstall.exe"
    Delete "$INSTDIR\LICENSE"
    Delete "$INSTDIR\README.md"
    Delete "$INSTDIR\CHANGELOG.md"
    RMDir    "$INSTDIR"

    Delete "$DESKTOP\${APP_NAME}.lnk"

    RMDir /r "$SMPROGRAMS\${APP_NAME}"
SectionEnd
