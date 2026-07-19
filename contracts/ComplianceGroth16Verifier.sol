// SPDX-License-Identifier: GPL-3.0
/*
    Copyright 2021 0KIMS association.

    This file is generated with [snarkJS](https://github.com/iden3/snarkjs).

    snarkJS is a free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    snarkJS is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
    or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
    License for more details.

    You should have received a copy of the GNU General Public License
    along with snarkJS. If not, see <https://www.gnu.org/licenses/>.
*/

pragma solidity >=0.7.0 <0.9.0;

contract Groth16Verifier {
    // Scalar field size
    uint256 constant r    = 21888242871839275222246405745257275088548364400416034343698204186575808495617;
    // Base field size
    uint256 constant q   = 21888242871839275222246405745257275088696311157297823662689037894645226208583;

    // Verification Key data
    uint256 constant alphax  = 12472620322045010560562896182411161621888606523387077394710167367595645298351;
    uint256 constant alphay  = 7728706611363036500028992605286739147205232143910140571979476857984653025610;
    uint256 constant betax1  = 2348405579188098141783765285903913049098442701404554644955040037666987689831;
    uint256 constant betax2  = 17077797765438261575931623921026356050984700696500127368723313647302640417416;
    uint256 constant betay1  = 61732165744645165370918613562405240234201122146277365200262257189364363604;
    uint256 constant betay2  = 14481065265074696565435350295117762887139350796180488266821522816919648422965;
    uint256 constant gammax1 = 11559732032986387107991004021392285783925812861821192530917403151452391805634;
    uint256 constant gammax2 = 10857046999023057135944570762232829481370756359578518086990519993285655852781;
    uint256 constant gammay1 = 4082367875863433681332203403145435568316851327593401208105741076214120093531;
    uint256 constant gammay2 = 8495653923123431417604973247489272438418190587263600148770280649306958101930;
    uint256 constant deltax1 = 13392949098640443543190534120813386195318178121254793394525890178102318691286;
    uint256 constant deltax2 = 7100328664757570436650549384348317323072017022391068172298747440024039375009;
    uint256 constant deltay1 = 2510310295728013673858388399397752975241859517320208341923483838136647622359;
    uint256 constant deltay2 = 20164737011753791565612153453913623954912891850600009404736878442378831334256;


    uint256 constant IC0x = 173877356498817930733012464503122276973750235550731383211269646001432624236;
    uint256 constant IC0y = 9556309092518540980774841172888531413847732911474001563592996213341415411477;

    uint256 constant IC1x = 2876686159599318815584561140784131200204277750344388825005538472800834417880;
    uint256 constant IC1y = 13890398262056321346452523747318350852926454180360271398363131990521399195969;

    uint256 constant IC2x = 21186899771237463291291421587352326045944054706243966777703493647402152917585;
    uint256 constant IC2y = 2582036751369065499138086476169702851408243192274768142829193292634689661453;

    uint256 constant IC3x = 9483834358811356909361967211484169777543847814647807321312798460602758436145;
    uint256 constant IC3y = 18811565908298235104637226894264411565319281896210610782527014740678469049864;

    uint256 constant IC4x = 13609419585694948773799432927442627424257965229904119821352910133193822551000;
    uint256 constant IC4y = 19064837652865503191384613253591667636719984343336260352001727449076094596355;

    uint256 constant IC5x = 19719553602783509625774903331013543099934260617009675614687264160217139835977;
    uint256 constant IC5y = 4100346778398997556559761017109182598893628867637524508467416719145532464873;

    uint256 constant IC6x = 16435979956375481433059595641662400867768265425606890626670479480968414583202;
    uint256 constant IC6y = 4457869591569141698664681523184795597651750208186493199534901798891294830355;

    uint256 constant IC7x = 17273845442604415526574704813977248686392775187256313962193972753331527311704;
    uint256 constant IC7y = 13266258927868738949692137763339894199921382574616992618293690085395240032102;

    uint256 constant IC8x = 4789017900770636734681157066594587337983045249097478269038232382916404473062;
    uint256 constant IC8y = 13112760536649999838855249059889519053627940690933461366306414549639204897871;

    uint256 constant IC9x = 18048054587033768731993413555563977091706608257392736797005526531973232940571;
    uint256 constant IC9y = 14680390396105877084729231825494983908116392028429622619604549707537987399034;

    uint256 constant IC10x = 9310826876837457529182774563151261353917499259550131470380737881567817532311;
    uint256 constant IC10y = 21531627398400555956837452703943280355291293598676622164762195508810474525100;

    uint256 constant IC11x = 18686219937941458902293972404015007294456415646623931049534928237075971583617;
    uint256 constant IC11y = 3340099601493639003444259245279813278788484106657071568285337134979005946541;


    // Memory data
    uint16 constant pVk = 0;
    uint16 constant pPairing = 128;

    uint16 constant pLastMem = 896;

    function verifyProof(uint[2] calldata _pA, uint[2][2] calldata _pB, uint[2] calldata _pC, uint[11] calldata _pubSignals) public view returns (bool) {
        assembly {
            function checkField(v) {
                if iszero(lt(v, r)) {
                    mstore(0, 0)
                    return(0, 0x20)
                }
            }

            // G1 function to multiply a G1 value(x,y) to value in an address
            function g1_mulAccC(pR, x, y, s) {
                let success
                let mIn := mload(0x40)
                mstore(mIn, x)
                mstore(add(mIn, 32), y)
                mstore(add(mIn, 64), s)

                success := staticcall(sub(gas(), 2000), 7, mIn, 96, mIn, 64)

                if iszero(success) {
                    mstore(0, 0)
                    return(0, 0x20)
                }

                mstore(add(mIn, 64), mload(pR))
                mstore(add(mIn, 96), mload(add(pR, 32)))

                success := staticcall(sub(gas(), 2000), 6, mIn, 128, pR, 64)

                if iszero(success) {
                    mstore(0, 0)
                    return(0, 0x20)
                }
            }

            function checkPairing(pA, pB, pC, pubSignals, pMem) -> isOk {
                let _pPairing := add(pMem, pPairing)
                let _pVk := add(pMem, pVk)

                mstore(_pVk, IC0x)
                mstore(add(_pVk, 32), IC0y)

                // Compute the linear combination vk_x

                g1_mulAccC(_pVk, IC1x, IC1y, calldataload(add(pubSignals, 0)))

                g1_mulAccC(_pVk, IC2x, IC2y, calldataload(add(pubSignals, 32)))

                g1_mulAccC(_pVk, IC3x, IC3y, calldataload(add(pubSignals, 64)))

                g1_mulAccC(_pVk, IC4x, IC4y, calldataload(add(pubSignals, 96)))

                g1_mulAccC(_pVk, IC5x, IC5y, calldataload(add(pubSignals, 128)))

                g1_mulAccC(_pVk, IC6x, IC6y, calldataload(add(pubSignals, 160)))

                g1_mulAccC(_pVk, IC7x, IC7y, calldataload(add(pubSignals, 192)))

                g1_mulAccC(_pVk, IC8x, IC8y, calldataload(add(pubSignals, 224)))

                g1_mulAccC(_pVk, IC9x, IC9y, calldataload(add(pubSignals, 256)))

                g1_mulAccC(_pVk, IC10x, IC10y, calldataload(add(pubSignals, 288)))

                g1_mulAccC(_pVk, IC11x, IC11y, calldataload(add(pubSignals, 320)))


                // -A
                mstore(_pPairing, calldataload(pA))
                mstore(add(_pPairing, 32), mod(sub(q, calldataload(add(pA, 32))), q))

                // B
                mstore(add(_pPairing, 64), calldataload(pB))
                mstore(add(_pPairing, 96), calldataload(add(pB, 32)))
                mstore(add(_pPairing, 128), calldataload(add(pB, 64)))
                mstore(add(_pPairing, 160), calldataload(add(pB, 96)))

                // alpha1
                mstore(add(_pPairing, 192), alphax)
                mstore(add(_pPairing, 224), alphay)

                // beta2
                mstore(add(_pPairing, 256), betax1)
                mstore(add(_pPairing, 288), betax2)
                mstore(add(_pPairing, 320), betay1)
                mstore(add(_pPairing, 352), betay2)

                // vk_x
                mstore(add(_pPairing, 384), mload(add(pMem, pVk)))
                mstore(add(_pPairing, 416), mload(add(pMem, add(pVk, 32))))


                // gamma2
                mstore(add(_pPairing, 448), gammax1)
                mstore(add(_pPairing, 480), gammax2)
                mstore(add(_pPairing, 512), gammay1)
                mstore(add(_pPairing, 544), gammay2)

                // C
                mstore(add(_pPairing, 576), calldataload(pC))
                mstore(add(_pPairing, 608), calldataload(add(pC, 32)))

                // delta2
                mstore(add(_pPairing, 640), deltax1)
                mstore(add(_pPairing, 672), deltax2)
                mstore(add(_pPairing, 704), deltay1)
                mstore(add(_pPairing, 736), deltay2)


                let success := staticcall(sub(gas(), 2000), 8, _pPairing, 768, _pPairing, 0x20)

                isOk := and(success, mload(_pPairing))
            }

            let pMem := mload(0x40)
            mstore(0x40, add(pMem, pLastMem))

            // Validate that all evaluations ∈ F

            checkField(calldataload(add(_pubSignals, 0)))

            checkField(calldataload(add(_pubSignals, 32)))

            checkField(calldataload(add(_pubSignals, 64)))

            checkField(calldataload(add(_pubSignals, 96)))

            checkField(calldataload(add(_pubSignals, 128)))

            checkField(calldataload(add(_pubSignals, 160)))

            checkField(calldataload(add(_pubSignals, 192)))

            checkField(calldataload(add(_pubSignals, 224)))

            checkField(calldataload(add(_pubSignals, 256)))

            checkField(calldataload(add(_pubSignals, 288)))

            checkField(calldataload(add(_pubSignals, 320)))


            // Validate all evaluations
            let isValid := checkPairing(_pA, _pB, _pC, _pubSignals, pMem)

            mstore(0, isValid)
             return(0, 0x20)
         }
     }
 }
