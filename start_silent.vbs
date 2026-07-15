Set objShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
objShell.CurrentDirectory = projectDir
objShell.Run """G:\Environments\Python12\pythonw.exe"" """ & projectDir & "\main.py"" --once", 0, False
