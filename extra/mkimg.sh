#!/bin/bash

# This script is to prepare and build a deb package of freecad Link branch, and
# build an AppImage using the deb package with asm3 installed
# 
# You need to setup pbuilder before being able to build a deb package
# indepedent of your own system. Run,
#
#   auto apt install gnupg pbuilder ubuntu-dev-tools apt-file eatmydata
#
# Create a pbuilder distribution. Since AppImage has better support for trusty,
# we shall stick to that. Run,
#
#   pbuilder-dist create trusty 
# 
# Create ~/.pbuilderrc with the following content
#
#   OTHERMIRROR="deb http://ppa.launchpad.net/freecad-maintainers/freecad-daily/ubuntu trusty main"
#   PTCACHEHARDLINK=no
#   CCACHEDIR=/var/cache/pbuilder/ccache
#   PACKAGES=eatmydata
#   EATMYDATA=yes
#
# Login to pbuilder to change a few setting,
#
#   pbuilder-dist trusty login --save-after-login
#
# You have just entered a chroot environement, now install eatmydata for better
# performance,
#
#   apt-get install eatmydata
#
# Add key for freecad-daily ppa, and exit
#
#   apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 83193AA3B52FF6FCF10A1BBF005EAE8119BB5BCA
#   exit 
#
# Update pbuilder source list
#   
#   pbuilder-dist trusty update --release-only
#
# Done. 
# 
#
# References
#
# http://packaging.ubuntu.com/html/getting-set-up.html
# https://askubuntu.com/questions/265703/how-to-do-a-pbuilder-dist-build-with-dependencies-in-a-ppa
# https://wiki.ubuntu.com/PbuilderHowto#pdebuild

set -ex

build=2
case "$1" in
    prepare)
        build=0
        ;;
    deb)
        build=1
        ;;
    *)
        cat << EOS
usage: $0 [prepare|deb]

prepare: only prepare a source repo of FreeCAD Link branch
deb: build deb package using pbuilder

Default behavior is to make sure repo is up to date, and deb package is built,
and then build the AppImage.

If everything runs find, the final AppImage will be located at img sub
directory.
EOS
esac

mkdir -p ./img
cd img
dir=$PWD

if ! test -d repo; then
    git clone https://github.com/realthunder/FreeCAD.git repo
    cd repo
    git checkout LinkStage3
else
    cd repo
    git pull
fi

mkdir -p build
cd build
cmake ..
cp ./src/Build/Version.h ../src/Build/
cd ..
rm -rf debian

cd $dir
if ! test -d gitpackaging; then
    git clone https://git.launchpad.net/~freecad-maintainers/+git/gitpackaging 
fi

cp -a gitpackaging/debian repo/

cd repo
echo y | debuild -S -d -us -uc

if [ $build -gt 0 ]; then
    gitdate=`date -d "$(git show -s --format=%aI)" +%Y%m%d%H%M`
    debdate=0
    debfile=$HOME/pbuilder/trusty_result/freecad-daily*amd64.deb
    if test -f $debfile; then
        debdate=`date -r $debfile +%Y%m%d%H%M`
    fi
    if [ $debdate -lt $gitdate ]; then
        pbuilder_dir=$HOME/pbuilder/trusty_result
        mkdir -p $pbuilder_dir/old
        mv $pbuilder_dir/freecad-daily* $pbuilder_dir/old/ || true
        pbuilder-dist trusty build ../*.dsc
    fi
fi

cd ..
if [ $build -gt 1 ]; then
    if ! test -d AppImages; then
        git clone https://github.com/realthunder/AppImages.git
        cd AppImages
        git checkout PostScript
    else
        cd AppImages
    fi
    
    bash -ex ./pkg2appimage recipes/FreeCAD-asm3.yml
    mv out/FreeCAD-asm3* ../
fi

