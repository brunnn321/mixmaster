# Arma la carpeta que empaqueta el instalador (build\) y compila MixMaster-Instalador.exe.
# Uso:  powershell -ExecutionPolicy Bypass -File instalador\construir.ps1
$ErrorActionPreference = 'Stop'
$raiz   = Split-Path $PSScriptRoot
$build  = Join-Path $PSScriptRoot 'build'
$app    = Join-Path $build 'MixMaster'
$torch  = Join-Path $build 'modelos\torch'
$hf     = Join-Path $build 'modelos\hf'

function Copiar($desde, $hasta, [string[]]$extra = @()) {
    robocopy $desde $hasta /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ @extra | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy fallo: $desde" }
}

if (Test-Path $build) { Remove-Item $build -Recurse -Force }
New-Item -ItemType Directory -Force $app, $torch, $hf | Out-Null

# 1. La app
Copy-Item "$raiz\main.py", "$raiz\MANUAL.md", "$raiz\README.md", "$raiz\requirements.txt" $app
Copiar "$raiz\mixmaster" "$app\mixmaster"
Copiar "$raiz\assets"    "$app\assets"
robocopy "$raiz\tempo" "$app\tempo" *.py *.md /NFL /NDL /NJH /NJS /NP | Out-Null

# 2. Configuracion: generos, referencias, perfiles y lo aprendido. Sin rutas ni historial de esta PC.
Copiar "$raiz\config\generos"  "$app\config\generos"
Copiar "$raiz\config\perfiles" "$app\config\perfiles"
Copy-Item "$raiz\config\aprendizaje.json", "$raiz\config\master.json", "$raiz\config\stems.json", "$raiz\config\perfil_bruno.md" "$app\config"
# version mini: solo masteriza, sin Herramientas, e importa paquetes de mejoras
'{"mini": true}' | Set-Content "$app\config\settings.json" -Encoding ascii

# 3. Python 3.14 portatil con todo lo que usa la app
$py = (Get-Content "$raiz\.venv\pyvenv.cfg" | Select-String '^home = (.+)$').Matches[0].Groups[1].Value.Trim()
Copiar $py "$app\python" @('Doc', 'include', 'Scripts')
Copiar "$raiz\.venv\Lib\site-packages" "$app\python\Lib\site-packages"

# 4. Python 3.12 portatil para MuScriptor (MIDI de Tempo Genius)
$py12 = (Get-Content "$raiz\tempo\.muscriptor\pyvenv.cfg" | Select-String '^home = (.+)$').Matches[0].Groups[1].Value.Trim()
Copiar $py12 "$app\tempo\.muscriptor" @('Doc', 'include', 'Scripts')
Copiar "$raiz\tempo\.muscriptor\Lib\site-packages" "$app\tempo\.muscriptor\Lib\site-packages"

# 5. ffmpeg (MP3, M4A, WMA)
$ff = Split-Path (Get-Item (Get-Command ffmpeg).Source).Target
New-Item -ItemType Directory -Force "$app\bin" | Out-Null
Copy-Item "$ff\ffmpeg.exe", "$ff\ffprobe.exe" "$app\bin"

# 6. Modelos: separador (htdemucs), pulso (beat_this) y MuScriptor
$env:TORCH_HOME = Join-Path $build 'torch_home'
& "$raiz\.venv\Scripts\python.exe" -c "from demucs.pretrained import get_model; get_model('htdemucs')"
if ($LASTEXITCODE -ne 0) { throw 'No se pudo bajar el modelo htdemucs' }
Copy-Item "$env:TORCH_HOME\hub\checkpoints\*" $torch
Copy-Item "$env:USERPROFILE\.cache\torch\hub\checkpoints\beat_this-final0.ckpt" $torch
Copiar "$env:USERPROFILE\.cache\huggingface\hub\models--MuScriptor--muscriptor-medium" "$hf\models--MuScriptor--muscriptor-medium"
Remove-Item $env:TORCH_HOME -Recurse -Force

# 7. Compilar el instalador
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
& $iscc "$PSScriptRoot\MixMaster.iss"
if ($LASTEXITCODE -ne 0) { throw 'Fallo la compilacion del instalador' }
