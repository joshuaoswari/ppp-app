Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

' Get the directory where this VBS script is located
strPath = objFSO.GetParentFolderName(WScript.ScriptFullName)
strExePath = strPath & "\HeartbeatAgent.exe"

' Check if EXE exists
If Not objFSO.FileExists(strExePath) Then
    MsgBox "HeartbeatAgent.exe not found!" & vbCrLf & vbCrLf & "Expected location: " & strExePath, vbCritical, "Error"
    WScript.Quit
End If

' Run the EXE completely hidden using WMI (more reliable than Shell.Run)
Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
Set objStartup = objWMIService.Get("Win32_ProcessStartup")
Set objConfig = objStartup.SpawnInstance_
objConfig.ShowWindow = 0  ' Hidden window

Set objProcess = objWMIService.Get("Win32_Process")
errReturn = objProcess.Create(strExePath, strPath, objConfig, intProcessID)
