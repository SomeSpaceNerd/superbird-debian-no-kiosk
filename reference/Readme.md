# Reference

These are the scripts and resources that I used to create the final debian image for the device, as well as some steps along the way.

Noteworthy scripts:

* `install_debootstrap.sh`, `debootstrap-superbird.tar.gz`, and `tools/` - superbird stock os does not include debootstrap, you can install this version if you want. this is not necessary. I used this method to bootstrap debian on the data partition initially, but it was much faster to iterate with an image file on my desktop machine and then write it to the partition
* `exploredev.py` used to explore things under `/sys/`, prints sections for each folder, shows (but does not follow) symlinks, shows values for any readable files

