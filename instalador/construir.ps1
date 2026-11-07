# Arma MixMaster mini (solo masteriza, sin herramientas en desarrollo) y compila MixMaster-Instalador.exe.
# Uso:  powershell -ExecutionPolicy Bypass -File instalador\construir.ps1
$ErrorActionPreference = 'Stop'
$raiz   = Split-Path $PSScriptRoot
$build  = Join-Path $PSScriptRoot 'build'
$app    = Join-Path $build 'MixMaster'
$hf     = Join-Path $build 'modelos\hf'

function Copiar($desde, $hasta, [string[]]$extra = @()) {
    robocopy $desde $hasta /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ @extra | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy fallo: $desde" }
}

if (Test-Path $build) { Remove-Item $build -Recurse -Force }
New-Item -ItemType Directory -Force $app, $hf | Out-Null

# 1. La app, sin las herramientas en desarrollo (Tempo Genius, convertidor, null test, A/B ciego,
#    notas, historial, arbol de generos, consola MM-01)
Copy-Item "$raiz\main.py", "$raiz\requirements.txt" $app
Copy-Item "$PSScriptRoot\MANUAL-mini.md" "$app\MANUAL.md"
$fuera = @('tempo_dialog.py', 'convertidor_dialog.py', 'convertidor.py', 'null_test.py',
           'ab_ciego_dialog.py', 'notas_dialog.py', 'historial_dialog.py', 'consola_web.py')
robocopy "$raiz\mixmaster" "$app\mixmaster" /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ web /XF @fuera | Out-Null
if ($LASTEXITCODE -ge 8) { throw 'robocopy fallo: mixmaster' }
Copiar "$raiz\assets" "$app\assets" @('consola')
Remove-Item "$app\assets\arbol_generos.html" -ErrorAction SilentlyContinue

# 2. Configuracion: generos, referencias, perfiles y lo aprendido. Sin rutas ni historial de esta PC.
Copiar "$raiz\config\generos"  "$app\config\generos"
Copiar "$raiz\config\perfiles" "$app\config\perfiles"
Copy-Item "$raiz\config\aprendizaje.json", "$raiz\config\master.json", "$raiz\config\stems.json" "$app\config"
'{"mini": true}' | Set-Content "$app\config\settings.json" -Encoding ascii

# 3. Python 3.14 portatil con todo lo que usa la app
$py = (Get-Content "$raiz\.venv\pyvenv.cfg" | Select-String '^home = (.+)$').Matches[0].Groups[1].Value.Trim()
Copiar $py "$app\python" @('Doc', 'include', 'Scripts')
# sin QML ni cabeceras de PySide6 (la app no los usa): sus rutas superan los 260 caracteres de Windows
Copiar "$raiz\.venv\Lib\site-packages" "$app\python\Lib\site-packages" @('qml', 'include', 'objects-Debug', 'tests')

# 4. Quitar del codigo los bloques de herramientas y comprobar que compila
& "$raiz\.venv\Scripts\python.exe" "$PSScriptRoot\limpiar_mini.py" $app
if ($LASTEXITCODE -ne 0) { throw 'La limpieza de la version mini fallo' }

# 5. ffmpeg (MP3, M4A, WMA)
$ff = Split-Path (Get-Item (Get-Command ffmpeg).Source).Target
New-Item -ItemType Directory -Force "$app\bin" | Out-Null
Copy-Item "$ff\ffmpeg.exe", "$ff\ffprobe.exe" "$app\bin"

# 6. Modelo del separador (htdemucs): demucs 4.1 lo baja desde Hugging Face
& "$raiz\.venv\Scripts\python.exe" -c "from demucs.pretrained import get_model; get_model('htdemucs')"
if ($LASTEXITCODE -ne 0) { throw 'No se pudo bajar el modelo htdemucs' }
Copiar "$env:USERPROFILE\.cache\huggingface\hub\models--adefossez--HTDemucs" "$hf\models--adefossez--HTDemucs"

# 7. Compilar el instalador
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
& $iscc "$PSScriptRoot\MixMaster.iss"
if ($LASTEXITCODE -ne 0) { throw 'Fallo la compilacion del instalador' }
Copy-Item "$PSScriptRoot\MANUAL-mini.md" "$PSScriptRoot\salida\MANUAL-MixMaster.md"
