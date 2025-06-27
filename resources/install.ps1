Write-Output "Installing Python package manager 'uv' from https://astral.sh/uv/ ..."
irm https://astral.sh/uv/install.ps1 | iex

# uv installer puts %USERPROFILE%\.local\bin into user-level PATH environment, but does not reload.

# Send notify message to interested clients that environment has changed.
Add-Type -Namespace Win32 -Name NativeMethods -MemberDefinition @"
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
"@
$HWND_BROADCAST = [IntPtr] 0xffff;
$WM_SETTINGCHANGE = 0x1a;
$result = [UIntPtr]::Zero
[void] ([Win32.Nativemethods]::SendMessageTimeout($HWND_BROADCAST, $WM_SETTINGCHANGE, [UIntPtr]::Zero, "Environment", 2, 5000, [ref] $result))

# Put new PATH into effect in current session.
$Env:Path = [Environment]::GetEnvironmentVariable("Path", "User")

Write-Output "Installing ChurchSong with uv ..."
& uv tool install --no-config --force --reinstall --python-preference only-managed ChurchSong

Write-Output "Installing Desktop shortcut to ChurchSong ..."
New-Item -ItemType Directory -Path "$Env:LOCALAPPDATA\ChurchSong" -Force | Out-Null
$webClient = New-Object System.Net.WebClient
$batchPath="$Env:LOCALAPPDATA\ChurchSong\ChurchSong.bat"
$iconPath="$Env:LOCALAPPDATA\ChurchSong\ChurchSong.ico"
$webClient.DownloadFile("https://raw.githubusercontent.com/sbellon/ChurchSong/refs/heads/main/resources/ChurchSong.bat", $batchPath)
$webClient.DownloadFile("https://raw.githubusercontent.com/sbellon/ChurchSong/refs/heads/main/resources/ChurchSong.ico", $iconPath)
$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut("$Env:USERPROFILE\Desktop\ChurchSong.lnk")
$Shortcut.TargetPath = $batchPath
$Shortcut.IconLocation = $iconPath
$Shortcut.Save()

Write-Output "Installing configuration template ..."
$configPath="$Env:LOCALAPPDATA\ChurchSong\config.toml"
$configUrl="https://raw.githubusercontent.com/sbellon/ChurchSong/refs/heads/main/resources/config.toml.example"
$webClient.DownloadFile($configUrl, $configPath)

New-Item -ItemType Directory -Path "$Env:USERPROFILE\Desktop\Data\Portraits" -Force | Out-Null
$webClient.DownloadFile("https://raw.githubusercontent.com/sbellon/ChurchSong/refs/heads/main/resources/Nobody.jpeg", "$Env:USERPROFILE\Desktop\Data\Portraits\Nobody.jpeg")

Write-Output "You have to adjust $configPath to make it work for you."

Read-Host "Done. Press Enter to exit"
