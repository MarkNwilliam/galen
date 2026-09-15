{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  packages = [
    pkgs.python311
    pkgs.python311Packages.pip
  ];
}
