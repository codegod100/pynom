{
  description = "pynom - Python Nix Output Monitor";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs, ... }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      
    in {
      packages = forAllSystems (system: let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
      in {
        default = self.packages.${system}.pynom;
        pynom = python.pkgs.buildPythonApplication {
          pname = "pynom";
          version = "0.1.0";
          pyproject = true;
          
          src = self;
          
          nativeBuildInputs = [
            python.pkgs.hatchling
          ];
          
          propagatedBuildInputs = with python.pkgs; [
            rich
            textual
          ];
        };
      });
      
      apps = forAllSystems (system: {
        default = self.apps.${system}.pynom;
        pynom = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/pynom";
        };
      });
      
      devShells = forAllSystems (system: let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
      in {
        default = pkgs.mkShell {
          packages = [
            (python.withPackages (ps: with ps; [
              rich
              textual
            ]))
            pkgs.uv
            pkgs.just
          ];
        };
      });
      
      overlays.default = final: prev: {
        pynom = self.packages.${final.system}.default;
      };
      
      homeManagerModules.default = { config, lib, pkgs, ... }:
        let cfg = config.programs.pynom;
        in {
          options.programs.pynom = {
            enable = lib.mkEnableOption "pynom - Python Nix Output Monitor";
          };
          config = lib.mkIf cfg.enable {
            home.packages = [ self.packages.${pkgs.system}.default ];
          };
        };
    };
}