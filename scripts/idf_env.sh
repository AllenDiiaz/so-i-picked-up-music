# Source this instead of export.sh when the default python3 is newer than the Python the
# ESP-IDF environment was installed with (e.g. after a Homebrew upgrade):
#
#   . scripts/idf_env.sh && idf.py build
#
# export.sh looks for ~/.espressif/python_env/idf<ver>_py<X.Y>_env matching the current
# python3. This puts a python3 of the already-installed X.Y first on PATH, so nothing has to be
# reinstalled. IDF_PATH defaults to ~/esp/esp-idf-v6.0.3.
: "${IDF_PATH:=$HOME/esp/esp-idf-v6.0.3}"
_idf_env=$(ls -d "$HOME"/.espressif/python_env/idf*_py*_env 2>/dev/null | tail -1)
if [ -n "$_idf_env" ]; then
    _idf_py=$(basename "$_idf_env" | sed -E 's/.*_py([0-9]+\.[0-9]+)_env/\1/')
    if [ "$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" != "$_idf_py" ] \
       && command -v "python$_idf_py" >/dev/null 2>&1; then
        _idf_shim="${TMPDIR:-/tmp}/idf_python_shim_$_idf_py"
        mkdir -p "$_idf_shim"
        ln -sf "$(command -v "python$_idf_py")" "$_idf_shim/python3"
        PATH="$_idf_shim:$PATH"
        echo "idf_env: using python$_idf_py for ESP-IDF (default python3 differs)"
    fi
fi
. "$IDF_PATH/export.sh" >/dev/null && echo "idf_env: ESP-IDF ready ($IDF_PATH)"
unset _idf_env _idf_py _idf_shim
