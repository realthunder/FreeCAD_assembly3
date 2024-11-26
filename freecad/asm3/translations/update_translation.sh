#!/usr/bin/env bash

# --------------------------------------------------------------------------------------------------
#
# Create, update and release translation files.
#
# Supported locales on FreeCAD <2024-11-25, FreeCADGui.supportedLocales(), total=44>:
# 	{'English': 'en', 'Afrikaans': 'af', 'Arabic': 'ar', 'Basque': 'eu', 'Belarusian': 'be',
# 	'Bulgarian': 'bg', 'Catalan': 'ca', 'Chinese Simplified': 'zh-CN',
# 	'Chinese Traditional': 'zh-TW', 'Croatian': 'hr', 'Czech': 'cs', 'Danish': 'da',
# 	 'Dutch': 'nl', 'Filipino': 'fil', 'Finnish': 'fi', 'French': 'fr', 'Galician': 'gl',
# 	'Georgian': 'ka', 'German': 'de', 'Greek': 'el', 'Hungarian': 'hu', 'Indonesian': 'id',
# 	'Italian': 'it', 'Japanese': 'ja', 'Kabyle': 'kab', 'Korean': 'ko', 'Lithuanian': 'lt',
# 	'Norwegian': 'no', 'Polish': 'pl', 'Portuguese': 'pt-PT', 'Portuguese, Brazilian': 'pt-BR',
# 	'Romanian': 'ro', 'Russian': 'ru', 'Serbian': 'sr', 'Serbian, Latin': 'sr-CS', 'Slovak': 'sk',
# 	'Slovenian': 'sl', 'Spanish': 'es-ES', 'Spanish, Argentina': 'es-AR', 'Swedish': 'sv-SE',
# 	'Turkish': 'tr', 'Ukrainian': 'uk', 'Valencian': 'val-ES', 'Vietnamese': 'vi'}
#
# NOTE: PREPARATION
# - Install Qt tools
# 	Debian-based (e.g., Ubuntu): $ sudo apt-get install qttools5-dev-tools pyqt6-dev-tools
# 	Fedora-based: $ sudo dnf install qt6-linguist qt6-devel
# 	Arch-based: $ sudo pacman -S qt6-tools python-pyqt6
# - Make the script executable
# 	$ chmod +x update_translation.sh
# - The script has to be executed within the `freecad/asm3/translations` directory.
# 	Executing the script with no flags invokes the help.
# 	$ ./update_translation.sh
#
# NOTE: WORKFLOW TRANSLATOR (LOCAL)
# - Execute the script passing the `-u` flag plus locale code as argument
# 	Only update the file(s) you're translating!
# 	$ ./update_translation.sh -u es-ES
# - Do the translation via Qt Linguist and use `File>Release`
# - If releasing with the script execute it passing the `-r` flag
# 	plus locale code as argument
# 	$ ./update_translation.sh -r es-ES
#
# NOTE: WORKFLOW MAINTAINER (CROWDIN)
# - Execute the script passing the '-U' flag
# 	$ ./update_translation.sh -U
# - Upload the updated file to Crowdin and wait for translators do their thing ;-)
# - Once done, download the translated files, copy them to `freecad/asm3/translations`
# 	and release all the files to update the changes
# 	$ ./update_translation.sh -R
#
# --------------------------------------------------------------------------------------------------

supported_locales=(
	"en" "af" "ar" "eu" "be" "bg" "ca" "zh-CN" "zh-TW" "hr"
	"cs" "da" "nl" "fil" "fi" "fr" "gl" "ka" "de" "el"
	"hu" "id" "it" "ja" "kab" "ko" "lt" "no" "pl" "pt-PT"
	"pt-BR" "ro" "ru" "sr" "sr-CS" "sk" "sl" "es-ES" "es-AR" "sv-SE"
	"tr" "uk" "val-ES" "vi"
)

is_locale_supported() {
	local locale="$1"
	for supported_locale in "${supported_locales[@]}"; do
		[ "$supported_locale" == "$locale" ] && return 0
	done
	return 1
}

update_locale() {
	local locale="$1"
	local u=${locale:+_} # Conditional underscore
	FILES="../*.py"

	# NOTE: Execute the right command depending on:
	# - if it's a locale file or the main, agnostic one
	[ ! -f "${WB}${u}${locale}.ts" ] && action="Creating" || action="Updating"
	echo -e "\033[1;34m\n\t<<< ${action} '${WB}${u}${locale}.ts' file >>>\n\033[m"
	if [ "$u" == "" ]; then
		eval $LUPDATE "$FILES" -ts "${WB}.ts" # locale-agnostic file
	else
		eval $LUPDATE "$FILES" -source-language en_US -target-language "${locale//-/_}" \
			-ts "${WB}_${locale}.ts"
	fi
}

help() {
	echo -e "\nDescription:"
	echo -e "\tCreate, update and release translation files."
	echo -e "\nUsage:"
	echo -e "\t./update_translation.sh [-R] [-U] [-r <locale>] [-u <locale>]"
	echo -e "\nFlags:"
	echo -e "  -R\n\tRelease all locales"
	echo -e "  -U\n\tUpdate main translation file (locale agnostic)"
	echo -e "  -r <locale>\n\tRelease the specified locale"
	echo -e "  -u <locale>\n\tUpdate strings for the specified locale"
}

# Main function ------------------------------------------------------------------------------------

LUPDATE=/usr/lib/qt6/bin/lupdate # from Qt6
# LUPDATE=lupdate                  # from Qt5
LRELEASE=/usr/lib/qt6/bin/lrelease # from Qt6
# LRELEASE=lrelease                 # from Qt5
WB="asm3"

# Enforce underscore on locales
sed -i '3s/-/_/' ${WB}*.ts

if [ $# -eq 1 ]; then
	if [ "$1" == "-R" ]; then
		find . -type f -name '*_*.ts' | while IFS= read -r file; do
			# Release all locales
			$LRELEASE -nounfinished "$file"
			echo
		done
	elif [ "$1" == "-U" ]; then
		# Update main file (agnostic)
		update_locale
	else
		help
	fi
elif [ $# -eq 2 ]; then
	LOCALE="$2"
	if is_locale_supported "$LOCALE"; then
		if [ "$1" == "-r" ]; then
			# Release locale (creation of *.qm file from *.ts file)
			$LRELEASE -nounfinished "${WB}_${LOCALE}.ts"
		elif [ "$1" == "-u" ]; then
			# Update main & locale files
			update_locale
			update_locale "$LOCALE"
		fi
	else
		echo "Verify your language code. Case sensitive."
		echo "If it's correct, ask a maintainer to add support for your language on FreeCAD."
		echo -e "Supported locales, '\033[1;34mFreeCADGui.supportedLocales()\033[m': \033[1;33m"
		for locale in $(printf "%s\n" "${supported_locales[@]}" | sort); do
			echo -n "$locale "
		done
		echo
	fi
else
	help
fi
